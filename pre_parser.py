import xml.etree.ElementTree as ET
import collections


class PresentationParser:
    """
    Parses the _pre.xml file.
    Its job is to discover all statements and return the
    ordered list of concepts for any given statement.
    """

    def __init__(self, pre_path, namespaces):
        print(f"  [PresentationParser] Initializing and discovering roles from {pre_path.name}...")
        self.ns = namespaces  # Get namespaces from orchestrator
        self.pre_path = pre_path
        self.discovered_roles = {}  # Our map: {friendly_name: role_uri}
        self.tree_pre = ET.parse(self.pre_path)
        self.root_pre = self.tree_pre.getroot()

        self._discover_roles()

    def _discover_roles(self):
        """Automatically builds the map of friendly names to roleURIs."""
        role_ref_tag = '{' + self.ns['link'] + '}roleRef'
        for role_ref in self.root_pre.iter(role_ref_tag):
            role_uri = role_ref.get('roleURI')
            href = role_ref.get('{' + self.ns['xlink'] + '}href')
            if role_uri and href and '#' in href:
                friendly_name = href.split('#')[-1]
                self.discovered_roles[friendly_name.lower()] = role_uri
        print(f"  [PresentationParser] Discovered {len(self.discovered_roles)} roles.")

    def find_statement_concepts(self, query):
        """
        This is the "path finder" for statements.
        It returns the ordered list of concepts for a matching statement.
        """

        # --- THIS IS THE FIX ---
        # Split the query into words for a more robust "AND" search
        query_words = query.lower().split()

        role_uri = None
        for friendly_name_lower, uri in self.discovered_roles.items():
            # Check if all query words are in the friendly name
            if all(word in friendly_name_lower for word in query_words):
                role_uri = uri
                break
                # --- END OF FIX ---

        if role_uri is None:
            return []  # This query is not a statement

        print(f"    ...Found matching statement. Getting order for {role_uri}...")

        presentation_link = None
        expected_tag = '{' + self.ns['link'] + '}presentationLink'
        expected_attr_key = '{' + self.ns['xlink'] + '}role'

        for child in self.root_pre:
            if child.tag == expected_tag and child.get(expected_attr_key) == role_uri:
                presentation_link = child
                break

        if presentation_link is None:
            return []

        loc_to_concept = {}
        for loc in presentation_link.iter('{' + self.ns['link'] + '}loc'):
            href = loc.get('{' + self.ns['xlink'] + '}href')
            label = loc.get('{' + self.ns['xlink'] + '}label')
            if href and label and '#' in href:
                loc_to_concept[label] = href.split('#')[-1]  # "us-gaap_Assets"

        arcs = collections.defaultdict(list)
        all_to_locs = set()
        for arc in presentation_link.iter('{' + self.ns['link'] + '}presentationArc'):
            from_loc = arc.get('{' + self.ns['xlink'] + '}from')
            to_loc = arc.get('{' + self.ns['xlink'] + '}to')
            order = float(arc.get('order', 1.0))
            if from_loc and to_loc and to_loc in loc_to_concept:
                arcs[from_loc].append((order, to_loc))
                all_to_locs.add(to_loc)

        root_locs = [loc for loc in arcs if loc not in all_to_locs]
        ordered_concepts = []

        def dfs_sort(loc_id):
            concept = loc_to_concept.get(loc_id)
            if concept:
                ordered_concepts.append(concept)
            for order, child_loc_id in sorted(arcs.get(loc_id, [])):
                dfs_sort(child_loc_id)

        for root_loc in root_locs:
            dfs_sort(root_loc)

        return ordered_concepts  # This is the "path"
