import csv
import pathlib
import sys
import re
import json
import xml.etree.ElementTree as ET
from datetime import datetime

# Use Decimal for high-precision financial math; float is insufficient
# and will produce rounding errors with large figures.
# Import InvalidOperation to catch non-numeric text processed by Decimal().
from decimal import Decimal, getcontext, InvalidOperation

# Set global precision for Decimal math. 38 is a safe, high-precision standard.
getcontext().prec = 38

# Import the worker classes. This script acts as the orchestrator.
from lab_parser import LabelParser
from pre_parser import PresentationParser
from htm_parser import HtmParser

# NOTE: The Calculation Parser (cal_parser.py) is not implemented here.
# To filter subtotals, we'd import and use CalParser to build a
# set of all parent concepts, which we could then check against.

"""
-------------------------------------------------------------------------------
Section 2: The Main XbrlParser (The "Orchestrator")
-------------------------------------------------------------------------------
"""


class XbrlParser:
    """
    This is the main "Orchestrator" class.
    Its job is to coordinate the "Worker" parsers (Label, Presentation, Htm).
    It handles pathing, namespace discovery, and dependency injection,
    and then manages the flow of data between the workers to produce the final CSV.
    """

    def __init__(self, htm_file_path):
        """
        Initializes the parser using just the HTM file path.
        This constructor infers all other required file paths (_lab, _pre)
        and builds the output directory name.
        """
        print("--- Initializing XbrlParser ---")

        # 1. Set paths
        self.htm_path = pathlib.Path(htm_file_path)
        if not self.htm_path.is_file():
            print(f"FATAL ERROR: File not found: {self.htm_path}")
            sys.exit(1)

        # Infer component file paths based on the HTM file's prefix.
        # e.g., 'goog-20250331_htm.xml' -> base_prefix 'goog-20250331'
        directory = self.htm_path.parent
        base_prefix = self.htm_path.stem.split('_')[0]

        # Use the base_prefix to find the associated linkbase files.
        self.lab_path = directory / f"{base_prefix}_lab.xml"
        self.pre_path = directory / f"{base_prefix}_pre.xml"

        print(f"  [XbrlParser] Inferred HTM path: {self.htm_path.name}")
        print(f"  [XbrlParser] Inferred LAB path: {self.lab_path.name}")
        print(f"  [XbrlParser] Inferred PRE path: {self.pre_path.name}")

        # 2. Check all files
        for f in [self.lab_path, self.pre_path]:
            if not f.is_file():
                print(f"FATAL ERROR: Inferred file not found: {f}")
                sys.exit(1)

        # 3. Create dynamic output folder name based on path components
        # Assumes a structure like .../TICKER/PERIOD/filename.xml
        # This makes the parser portable.
        ticker = self.htm_path.parts[-3].upper()
        report_date = base_prefix.split('-')[1]
        folder_name = f"financial_statements_{ticker}_{report_date}"

        self.output_dir = pathlib.Path(folder_name)
        self.output_dir.mkdir(exist_ok=True)
        print(f"  [XaParser] Output directory set to: {self.output_dir}")

        # 4. Discover namespaces (critical step)
        # Namespaces (e.g., 'us-gaap') are not consistent across filings,
        # so we *must* discover them from the files themselves.
        self.ns = self._discover_namespaces()
        print(f"  [XbrlParser] Discovered {len(self.ns)} total namespaces.")
        
        # Set default fallbacks, as these are almost universal
        self.ns.setdefault('link', 'http://www.xbrl.org/2003/linkbase')
        self.ns.setdefault('xlink', 'http://www.w3.org/1999/xlink')
        self.ns.setdefault('xbrli', 'http://www.xbrl.org/2003/instance')

        # 5. Create instances of component parsers (Dependency Injection)
        # We pass the shared, discovered namespaces to each worker.
        self.lab_parser = LabelParser(self.lab_path, self.ns)
        self.pre_parser = PresentationParser(self.pre_path, self.ns)
        self.htm_parser = HtmParser(self.htm_path, self.ns)

        print("--- Parser is ready ---")

    def _discover_namespaces(self):
        """
        Parses all XML files to find all 'xmlns' definitions.
        This is robust, as namespaces can be defined in any file.
        """
        print("  [XbrlParser] Discovering namespaces (Robust Method)...")
        namespaces = {}

        # Iterate all relevant files
        for xml_file in [self.lab_path, self.pre_path, self.htm_path]:
            # iterparse is memory-efficient and finds 'start-ns' events
            events = ET.iterparse(xml_file, events=['start-ns'])
            for event, (prefix, uri) in events:
                if prefix:
                    namespaces[prefix] = uri
                else:
                    # 'default' namespace (no prefix)
                    namespaces['default'] = uri

        # The 'xbrli' namespace (for <context> tags) is often the 'default'
        # in the HTM file, so we map it explicitly.
        if 'xbrli' not in namespaces and 'default' in namespaces:
            namespaces['xbrli'] = namespaces['default']

        return namespaces

    def _find_relevant_contexts(self, query, num_contexts=2):
        """
        Finds the most recent context IDs based on the query.
        This contains key business logic:
        - 'balance sheet' needs 'instant' contexts (a point in time).
        - 'income statement' needs 'duration' contexts (a period of time).
        """
        query_lower = query.lower()
        if 'balance sheet' in query_lower or 'goodwill' in query_lower:
            # Concepts on a balance sheet are "point in time"
            target_type = 'instant'
        else:
            # Concepts on income/cash flow are "over a period"
            target_type = 'duration'

        print(f"    ...Query type is '{target_type}'. Finding most recent contexts...")

        # Get the pre-parsed contexts from the HtmParser
        all_contexts = self.htm_parser.contexts
        filtered_contexts = []
        for ctx_id, info in all_contexts.items():
            if info.get('type') == target_type:
                filtered_contexts.append({'id': ctx_id, 'date': info['date']})

        if not filtered_contexts:
            print(f"    ...WARNING: No contexts found for type '{target_type}'.")
            return []

        # Helper to parse ISO format dates for sorting
        def safe_date_parse(c):
            return datetime.fromisoformat(c['date'])

        # Sort by date, newest first
        filtered_contexts.sort(key=safe_date_parse, reverse=True)

        # De-duplicate by date. We only want the *most recent* contexts,
        # as filings often have multiple contexts for the same date
        # (e.g., one with dimensions, one without). This gets the top N unique dates.
        top_contexts = []
        seen_dates = set()
        for ctx in filtered_contexts:
            if ctx['date'] not in seen_dates:
                top_contexts.append(ctx['id'])
                seen_dates.add(ctx['date'])
            # Stop once we have the number of contexts we need
            if len(top_contexts) >= num_contexts:
                break

        print(f"    ...Found contexts: {top_contexts}")
        return top_contexts

    def parse(self, query_list):
        """
        The main public method. Processes a list of mixed queries.
        This orchestrates the entire workflow.
        """
        print(f"\n--- Starting to Parse {len(query_list)} Queries ---")

        for query in query_list:
            print(f"\n  Processing Query: '{query}'")

            # 1. Try to find concepts as a "Statement" (from pre_parser)
            # This returns an ordered list if it's a known statement.
            concept_path = self.pre_parser.find_statement_concepts(query)

            # 2. If not a statement, search labels (from lab_parser)
            # This returns a list of one or more matching concepts.
            if not concept_path:
                print(f"    ...Not a statement. Searching labels...")
                concept_path = self.lab_parser.find_concepts_by_query(query)

            # 3. If no path found, warn and skip
            if not concept_path:
                print(f"    ...WARNING: No concepts found for query '{query}'. Skipping.")
                continue

            print(f"    ...Found {len(concept_path)} concepts for this query.")

            # 4. Find relevant time contexts (from htm_parser)
            context_ids = self._find_relevant_contexts(query)
            if not context_ids:
                print(f"    ...WARNING: Could not find relevant contexts for '{query}'. Skipping.")
                continue

            # 5. Get the actual financial data (from htm_parser)
            data_rows = self.htm_parser.get_data(concept_path, context_ids)
            
            # 6. Write to CSV
            self._write_csv(query, data_rows, context_ids)

        print("\n--- All Parsing Complete ---")

    def _write_csv(self, query, data_rows, context_ids):
        """
        Internal helper to write a single CSV file.
        Contains the critical scaling and data conversion logic.
        """

        # Sanitize query to create a valid filename
        filename = re.sub(r'[^a-z0-9_]+', '', query.lower().replace(' ', '_')) + '.csv'
        output_path = self.output_dir / filename

        # Get date headers (e.g., '2025-03-31') from context IDs (e.g., 'c-123')
        date_headers = self.htm_parser.get_context_dates(context_ids)
        header = ['Line Item'] + date_headers

        def _get_scaled_numeric(value_obj):
            """
            This is the core numerical logic.
            Applies scale and decimals to the base value using Decimal math.
            e.g., value=100, scale=6 -> 100,000,000
            e.g., value=100, decimals=-3 (thousands) -> 100,000
            """
            value_str = value_obj.get('value')

            if not value_str or value_str == 'N/A':
                return 'N/A'  # Pass through 'N/A'

            # Clean the string for Decimal conversion
            cleaned_str = value_str.replace(',', '')
            is_negative = False
            # Handle standard accounting format for negatives
            if cleaned_str.startswith('(') and cleaned_str.endswith(')'):
                is_negative = True
                cleaned_str = cleaned_str.strip('()')

            try:
                # Use Decimal for high-precision math.
                base_value = Decimal(cleaned_str)

                # Get scale/decimals, defaulting to '0' if not provided
                scale_str = value_obj.get('scale', '0')
                decimals_str = value_obj.get('decimals', '0')

                # 'INF' is a valid XBRL value for decimals, treat as 0
                if decimals_str.lower() == 'inf':
                    decimals_str = '0'

                scale = int(scale_str)
                decimals = int(decimals_str)

                # This logic is key:
                # 'scale' is a multiplier (10^scale)
                # 'decimals' is a *divider* (10^decimals), so we subtract
                # A negative 'decimals' (e.g., -3 for thousands) becomes a multiplier
                # Final value = base_value * (10 ** scale) * (10 ** -decimals)
                # ...which simplifies to:
                total_power = scale - decimals
                
                # Apply the scaling
                scaled_value = base_value * (Decimal(10) ** total_power)

                final_value = -scaled_value if is_negative else scaled_value

                # Return as int if it's a whole number, else float
                if final_value == final_value.to_integral_value():
                    return int(final_value)
                else:
                    return float(final_value)

            except (ValueError, TypeError, InvalidOperation):
                # This block catches non-numeric text (e.g., "See Note 5")
                # Truncate for cleaner CSV output
                return (value_str[:75] + '...') if len(value_str) > 75 else value_str

        with open(output_path, 'w', newline='', encoding='utf-8') as f:
            writer = csv.writer(f)
            writer.writerow(header)

            for data in data_rows:
                # ---
                # NOTE: NO FILTERING LOGIC
                # This is where we would check against a CalParser index
                # if data['concept'] in self.cal_parser.parent_concepts:
                #     continue
                # ---

                # Get the human-readable label (e.g., "Revenues")
                label = self.lab_parser.get_label_for_concept(data['concept'])
                row = [label]

                # Append the scaled numeric value for each context
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
    # This is the only path you need to set manually.
    # The script assumes a .../TICKER/PERIOD/filename.xml structure
    # to auto-generate the output folder name.
    
    # Example for Google:
    # HTM_FILE_PATH = 'goog/Q2/goog-20250331_htm.xml'
    #
    # Example for Meta:
    # HTM_FILE_PATH = 'meta/Q2/meta-20250331_htm.xml'
    
    HTM_FILE_PATH = 'meta/Q2/meta-20250331_htm.xml'  # <--- CHANGE THIS

    # 2. Define the list of queries you want to run
    # These can be statement names or individual concept labels.
    queries_to_run = [
        'income statement',
        'balance sheet',
        'earnings per share',
        'cash flow',
        'Goodwill'
    ]

    # 3. Create the main parser.
    # This single call initializes all sub-parsers and does discovery.
    parser = XbrlParser(
        htm_file_path=HTM_FILE_PATH
    )

    # 4. Run the job
    parser.parse(queries_to_run)
