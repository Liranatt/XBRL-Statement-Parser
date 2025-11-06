import csv
import pathlib
import sys
import re
import json
import xml.etree.ElementTree as ET
from datetime import datetime
# ---
# ⚠️ FIX 1: Import InvalidOperation
# ---
from decimal import Decimal, getcontext, InvalidOperation

# Set precision for Decimal math
getcontext().prec = 38

# Import the worker classes from their files
from lab_parser import LabelParser
from pre_parser import PresentationParser
from htm_parser import HtmParser

# --- NO CAL_PARSER ---

"""
-------------------------------------------------------------------------------
Section 2: The Main XbrlParser (The "Orchestrator")
-------------------------------------------------------------------------------
"""


class XbrlParser:

    def __init__(self, htm_file_path):
        """
        Initializes the parser using just the HTM file path.
        Infers other file paths and the output folder name.
        """
        print("--- Initializing XbrlParser ---")

        # 1. Set paths
        self.htm_path = pathlib.Path(htm_file_path)
        if not self.htm_path.is_file():
            print(f"FATAL ERROR: File not found: {self.htm_path}")
            sys.exit(1)

        directory = self.htm_path.parent
        base_prefix = self.htm_path.stem.split('_')[0]

        self.lab_path = directory / f"{base_prefix}_lab.xml"
        self.pre_path = directory / f"{base_prefix}_pre.xml"
        # --- NO CAL_PATH ---

        print(f"  [XbrlParser] Inferred HTM path: {self.htm_path.name}")
        print(f"  [XbrlParser] Inferred LAB path: {self.lab_path.name}")
        print(f"  [XbrlParser] Inferred PRE path: {self.pre_path.name}")

        # 2. Check all files
        for f in [self.lab_path, self.pre_path]:  # --- NO CAL_PATH ---
            if not f.is_file():
                print(f"FATAL ERROR: Inferred file not found: {f}")
                sys.exit(1)

        # 3. Create dynamic output folder name
        ticker = self.htm_path.parts[-3].upper()
        report_date = base_prefix.split('-')[1]
        folder_name = f"financial_statements_{ticker}_{report_date}"

        self.output_dir = pathlib.Path(folder_name)
        self.output_dir.mkdir(exist_ok=True)
        print(f"  [XaParser] Output directory set to: {self.output_dir}")

        # 4. Discover namespaces
        self.ns = self._discover_namespaces()
        print(f"  [XbrlParser] Discovered {len(self.ns)} total namespaces.")
        self.ns.setdefault('link', 'http://www.xbrl.org/2003/linkbase')
        self.ns.setdefault('xlink', 'http://www.w3.org/1999/xlink')
        self.ns.setdefault('xbrli', 'http://www.xbrl.org/2003/instance')

        # 5. Create instances of component parsers
        self.lab_parser = LabelParser(self.lab_path, self.ns)
        self.pre_parser = PresentationParser(self.pre_path, self.ns)
        self.htm_parser = HtmParser(self.htm_path, self.ns)
        # --- NO CAL_PARSER ---

        print("--- Parser is ready ---")

    def _discover_namespaces(self):
        print("  [XbrlParser] Discovering namespaces (Robust Method)...")
        namespaces = {}

        for xml_file in [self.lab_path, self.pre_path, self.htm_path]:  # --- NO CAL_PATH ---
            events = ET.iterparse(xml_file, events=['start-ns'])
            for event, (prefix, uri) in events:
                if prefix:
                    namespaces[prefix] = uri
                else:
                    namespaces['default'] = uri

        if 'xbrli' not in namespaces and 'default' in namespaces:
            namespaces['xbrli'] = namespaces['default']

        return namespaces

    def _find_relevant_contexts(self, query, num_contexts=2):
        """
        Finds the most recent context IDs based on the query.
        'balance sheet' needs 'instant' contexts.
        Others ('income statement', 'cash flow') need 'duration'.
        """
        query_lower = query.lower()
        if 'balance sheet' in query_lower or 'goodwill' in query_lower:
            target_type = 'instant'
        else:
            target_type = 'duration'

        print(f"    ...Query type is '{target_type}'. Finding most recent contexts...")

        all_contexts = self.htm_parser.contexts
        filtered_contexts = []
        for ctx_id, info in all_contexts.items():
            if info.get('type') == target_type:
                filtered_contexts.append({'id': ctx_id, 'date': info['date']})

        if not filtered_contexts:
            print(f"    ...WARNING: No contexts found for type '{target_type}'.")
            return []

        def safe_date_parse(c):
            return datetime.fromisoformat(c['date'])

        filtered_contexts.sort(key=safe_date_parse, reverse=True)

        top_contexts = []
        seen_dates = set()
        for ctx in filtered_contexts:
            if ctx['date'] not in seen_dates:
                top_contexts.append(ctx['id'])
                seen_dates.add(ctx['date'])
            if len(top_contexts) >= num_contexts:
                break

        print(f"    ...Found contexts: {top_contexts}")
        return top_contexts

    def parse(self, query_list):
        """
        The main public method. Processes a list of mixed queries.
        """
        print(f"\n--- Starting to Parse {len(query_list)} Queries ---")

        for query in query_list:
            print(f"\n  Processing Query: '{query}'")

            concept_path = self.pre_parser.find_statement_concepts(query)
            if not concept_path:
                print(f"    ...Not a statement. Searching labels...")
                concept_path = self.lab_parser.find_concepts_by_query(query)

            if not concept_path:
                print(f"    ...WARNING: No concepts found for query '{query}'. Skipping.")
                continue

            print(f"    ...Found {len(concept_path)} concepts for this query.")

            context_ids = self._find_relevant_contexts(query)
            if not context_ids:
                print(f"    ...WARNING: Could not find relevant contexts for '{query}'. Skipping.")
                continue

            data_rows = self.htm_parser.get_data(concept_path, context_ids)
            self._write_csv(query, data_rows, context_ids)

        print("\n--- All Parsing Complete ---")

    def _write_csv(self, query, data_rows, context_ids):
        """
        Internal helper to write a single CSV file.
        Scales and converts values to numbers.
        """

        filename = re.sub(r'[^a-z0-9_]+', '', query.lower().replace(' ', '_')) + '.csv'
        output_path = self.output_dir / filename

        date_headers = self.htm_parser.get_context_dates(context_ids)
        header = ['Line Item'] + date_headers

        def _get_scaled_numeric(value_obj):
            value_str = value_obj.get('value')

            if not value_str or value_str == 'N/A':
                return 'N/A'  # <-- Keep N/A as 'N/A'

            cleaned_str = value_str.replace(',', '')
            is_negative = False
            if cleaned_str.startswith('(') and cleaned_str.endswith(')'):
                is_negative = True
                cleaned_str = cleaned_str.strip('()')

            try:
                # Use Decimal for high-precision math
                base_value = Decimal(cleaned_str)

                # Get scale and decimals, defaulting to '0'
                scale_str = value_obj.get('scale', '0')
                decimals_str = value_obj.get('decimals', '0')

                # Handle edge case where decimals is 'INF'
                if decimals_str.lower() == 'inf':
                    decimals_str = '0'

                scale = int(scale_str)
                decimals = int(decimals_str)

                # Apply scaling
                total_scale = scale + decimals

                scaled_value = base_value * (Decimal(10) ** total_scale)

                final_value = -scaled_value if is_negative else scaled_value

                if final_value == final_value.to_integral_value():
                    return int(final_value)
                else:
                    return float(final_value)

            # ---
            # ⚠️ FIX 2: Catch InvalidOperation
            # ---
            except (ValueError, TypeError, InvalidOperation):
                # If it's text (e.g. "See Note 5" or a TextBlock),
                # just return the original text, but truncated
                return (value_str[:75] + '...') if len(value_str) > 75 else value_str

        with open(output_path, 'w', newline='', encoding='utf-8') as f:
            writer = csv.writer(f)
            writer.writerow(header)

            for data in data_rows:
                # ---
                # ⚠️ NO FILTERING LOGIC ⚠️
                # ---

                label = self.lab_parser.get_label_for_concept(data['concept'])
                row = [label]

                for ctx_id in context_ids:
                    value_object = data.get(ctx_id)
                    row.append(_get_scaled_numeric(value_object))

                writer.writerow(row)

        print(f"    ...Success! File '{filename}' created.")


"""
-------------------------------------------------------------------------------
Section 3: How to Use the Class
-------------------------------------------------------------------------------
"""

if __name__ == "__main__":
    # 1. Define the HTM file path
    # Make sure it follows the .../TICKER/QUARTER/filename.xml structure
    #
    # ---
    # Example for Google:
    # HTM_FILE_PATH = 'goog/Q2/goog-20250331_htm.xml'
    #
    # Example for Meta:
    # HTM_FILE_PATH = 'meta/Q2/meta-20250331_htm.xml'
    # ---
    HTM_FILE_PATH = 'meta/Q2/meta-20250331_htm.xml'  # <--- CHANGE THIS

    # 2. Define the list of queries you want to run
    queries_to_run = [
        'income statement',
        'balance sheet',
        'earnings per share',
        'cash flow',
        'Goodwill'
    ]

    # 3. Create the main parser.
    parser = XbrlParser(
        htm_file_path=HTM_FILE_PATH
    )

    # 4. Run the job
    parser.parse(queries_to_run)