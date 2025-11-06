import xml.etree.ElementTree as ET
import collections
import json


class HtmParser:
    """
    Parses the _htm.xml file.
    Its job is to be the "database" that holds all context
    definitions and all financial values, *including scaling*.
    """

    def __init__(self, htm_path, namespaces):
        print(f"  [HtmParser] Initializing and loading data from {htm_path.name}...")
        self.ns = namespaces

        # self.contexts stores: {context_id: {'type': '...', 'date': '...'}}
        self.contexts = {}

        # ---
        # ⚠️ MODIFICATION: self.values now stores a rich dictionary
        # {concept: {context_id: {'value': '...', 'decimals': '...', 'scale': '...'}}}
        # ---
        self.values = collections.defaultdict(lambda: collections.defaultdict(dict))
        self.value_concepts_loaded = set()

        tree_htm = ET.parse(htm_path)
        root_htm = tree_htm.getroot()
        xbrli_uri = self.ns.get('xbrli', self.ns.get('default'))

        # 1. Parse <context> elements
        for context in root_htm.iter('{' + xbrli_uri + '}context'):
            context_id = context.get('id')
            period_elem = context.find('.//{' + xbrli_uri + '}period')
            if context_id and period_elem is not None:
                instant = period_elem.find('{' + xbrli_uri + '}instant')
                end_date = period_elem.find('{' + xbrli_uri + '}endDate')
                start_date = period_elem.find('{' + xbrli_uri + '}startDate')

                if instant is not None:
                    self.contexts[context_id] = {
                        'type': 'instant',
                        'date': instant.text
                    }
                elif end_date is not None:
                    self.contexts[context_id] = {
                        'type': 'duration',
                        'date': end_date.text,
                        'start': start_date.text if start_date is not None else 'N/A'
                    }

        print(f"  [HtmParser] Loaded {len(self.contexts)} contexts.")

        # 2. Parse all data elements
        for element in root_htm.iter():
            context_ref = element.get('contextRef')
            if context_ref and context_ref in self.contexts:
                tag_parts = element.tag.split('}')
                if len(tag_parts) == 2:
                    tag_uri = tag_parts[0].strip('{')
                    tag_name = tag_parts[1]

                    concept_prefix = self._find_prefix(tag_uri)
                    if concept_prefix:
                        concept_name = f"{concept_prefix}_{tag_name}"

                        # ---
                        # ⚠️ MODIFICATION: Get scaling attributes
                        # ---
                        value = element.text
                        # Default to 0 (power of 1) if 'decimals' is missing
                        decimals = element.get('decimals', '0')
                        # Default to 0 (power of 1) if 'scale' is missing
                        scale = element.get('scale', '0')

                        # Store the rich data object
                        self.values[concept_name][context_ref] = {
                            'value': value,
                            'decimals': decimals,
                            'scale': scale
                        }
                        self.value_concepts_loaded.add(concept_name)

        print(f"  [HtmParser] Loaded data for {len(self.value_concepts_loaded)} unique concepts.")

    def _find_prefix(self, uri):
        """Helper to find the prefix for a given namespace URI."""
        for prefix, ns_uri in self.ns.items():
            if ns_uri == uri:
                return prefix
        return None

    def get_data(self, concept_list, context_ids):
        """
        The main data retrieval method.
        Returns all found data for a list of concepts.
        """
        results = []
        for concept in concept_list:
            row_data = {'concept': concept}
            value_map = self.values.get(concept, {})

            for ctx_id in context_ids:
                # ---
                # ⚠️ MODIFICATION: Pass the *entire value object*
                # or a default 'N/A' object
                # ---
                default_val = {'value': 'N/A', 'decimals': '0', 'scale': '0'}
                row_data[ctx_id] = value_map.get(ctx_id, default_val)

            results.append(row_data)
        return results

    def get_context_dates(self, context_ids):
        """Helper to get a clean date for a CSV header."""
        date_list = []
        for ctx_id in context_ids:
            date_list.append(self.contexts.get(ctx_id, {}).get('date', ctx_id))
        return date_list

    def get_value_by_concept(self, concept_name):
        """
        Fetches the first available value for a specific concept.
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