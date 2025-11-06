import xml.etree.ElementTree as ET
import collections
import json


class HtmParser:
    """
    Parses the _htm.xml file (the "instance" document).
    Its job is to be the "database" that holds all context
    definitions (time periods) and all financial values (facts).
    It pre-parses and caches all data for fast retrieval.
    """

    def __init__(self, htm_path, namespaces):
        print(f"  [HtmParser] Initializing and loading data from {htm_path.name}...")
        self.ns = namespaces

        # self.contexts stores: {context_id: {'type': '...', 'date': '...'}}
        self.contexts = {}

        # self.values stores a rich dictionary:
        # {concept: {context_id: {'value': '...', 'decimals': '...', 'scale': '...'}}}
        # This structure is a nested defaultdict:
        # 1. Key: concept (e.g., "us-gaap_Assets")
        # 2. Key: context_id (e.g., "c-1")
        # 3. Value: The data object {'value': ..., 'scale': ...}
        self.values = collections.defaultdict(lambda: collections.defaultdict(dict))
        self.value_concepts_loaded = set() # Just for logging

        tree_htm = ET.parse(htm_path)
        root_htm = tree_htm.getroot()
        # Find the xbrli namespace URI, which is critical for parsing <context>
        # Fallback to 'default' if 'xbrli' isn't explicitly prefixed.
        xbrli_uri = self.ns.get('xbrli', self.ns.get('default'))

        # 1. Parse <context> elements
        for context in root_htm.iter('{' + xbrli_uri + '}context'):
            context_id = context.get('id')
            period_elem = context.find('.//{' + xbrli_uri + '}period')
            if context_id and period_elem is not None:
                # Find 'instant' (for balance sheet)
                instant = period_elem.find('{' + xbrli_uri + '}instant')
                # Find 'endDate' (for income statement/cash flow)
                end_date = period_elem.find('{' + xbrli_uri + '}endDate')
                start_date = period_elem.find('{' + xbrli_uri + '}startDate')

                if instant is not None:
                    # This is a "point in time" context
                    self.contexts[context_id] = {
                        'type': 'instant',
                        'date': instant.text
                    }
                elif end_date is not None:
                    # This is a "duration" context
                    self.contexts[context_id] = {
                        'type': 'duration',
                        'date': end_date.text,
                        'start': start_date.text if start_date is not None else 'N/A'
                    }

        print(f"  [HtmParser] Loaded {len(self.contexts)} contexts.")

        # 2. Parse all data elements (facts)
        for element in root_htm.iter():
            context_ref = element.get('contextRef')
            # Filter for elements that are facts (have a contextRef)
            if context_ref and context_ref in self.contexts:
                # Get the tag (e.g., "{http://fasb.org/us-gaap/2025}Assets")
                tag_parts = element.tag.split('}')
                if len(tag_parts) == 2:
                    tag_uri = tag_parts[0].strip('{')
                    tag_name = tag_parts[1]

                    # Reverse-lookup the prefix (e.g., "us-gaap") from the URI
                    concept_prefix = self._find_prefix(tag_uri)
                    if concept_prefix:
                        # Re-create the prefixed concept name
                        concept_name = f"{concept_prefix}_{tag_name}"

                        # Get scaling attributes. This is critical.
                        value = element.text
                        # Default to '0' (which means 10^0, or 1) if missing
                        decimals = element.get('decimals', '0')
                        scale = element.get('scale', '0')

                        # Store the rich data object.
                        # We MUST store scale/decimals alongside the value.
                        self.values[concept_name][context_ref] = {
                            'value': value,
                            'decimals': decimals,
                            'scale': scale
                        }
                        self.value_concepts_loaded.add(concept_name)

        print(f"  [HtmParser] Loaded data for {len(self.value_concepts_loaded)} unique concepts.")

    def _find_prefix(self, uri):
        """Helper to find the prefix (e.g., 'us-gaap') for a given namespace URI."""
        for prefix, ns_uri in self.ns.items():
            if ns_uri == uri:
                return prefix
        return None # No prefix found

    def get_data(self, concept_list, context_ids):
        """
        The main data retrieval method.
        Returns all found data for a list of concepts and contexts.
        """
        results = []
        for concept in concept_list:
            row_data = {'concept': concept}
            # Get the map of {context_id: value_obj} for this concept
            # Use .get() with a default empty dict to avoid errors
            value_map = self.values.get(concept, {})

            for ctx_id in context_ids:
                # Pass the *entire value object* or a default 'N/A' object
                # This ensures the main parser always gets a valid object
                # to pass to its scaling function, avoiding KeyError.
                default_val = {'value': 'N/A', 'decimals': '0', 'scale': '0'}
                row_data[ctx_id] = value_map.get(ctx_id, default_val)

            results.append(row_data)
        return results

    def get_context_dates(self, context_ids):
        """Helper to get a clean date for a CSV header."""
        date_list = []
        for ctx_id in context_ids:
            # Fallback to the ID itself if not found (shouldn't happen)
            date_list.append(self.contexts.get(ctx_id, {}).get('date', ctx_id))
        return date_list

    def get_value_by_concept(self, concept_name):
        """
        Fetches the first available value for a specific concept.
        (Mostly useful for debugging).
        """
        value_map = self.values.get(concept_name)
        if not value_map:
            print(f"    ...[HtmParser] WARN: Concept '{concept_name}' not found in values.")
            return None
        try:
            # Return the first *value string*
            return next(iter(value_map.values())).get('value')
        except StopIteration:
            return None
