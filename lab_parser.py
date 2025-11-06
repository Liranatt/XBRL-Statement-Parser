import xml.etree.ElementTree as ET


class LabelParser:
    """
    Parses the _lab.xml file.
    Its job is to build a two-way index (hash map) to quickly find
    concepts by their human-readable labels and vice-versa.
    It's a "dictionary" for the XBRL concepts.
    """

    def __init__(self, lab_path, namespaces):
        print(f"  [LabelParser] Initializing and building index from {lab_path.name}...")
        self.ns = namespaces  # Get namespaces from orchestrator
        self.label_to_concept = {}  # Search index (e.g., "assets" -> "us-gaap_Assets")
        self.concept_to_label = {}  # Lookup index (e.g., "us-gaap_Assets" -> "Assets")

        tree_lab = ET.parse(lab_path)
        root_lab = tree_lab.getroot()

        # The _lab.xml file is a "linkbase". We have to resolve the relationships
        # in three steps, as the data is heavily normalized:
        
        # 1. Map <loc> 'label' (e.g., "loc_1") to concept 'href' (e.g., "us-gaap_Assets")
        loc_to_concept = {}
        # Find all <loc> elements using the 'link' namespace
        for loc in root_lab.iter('{' + self.ns['link'] + '}loc'):
            # Use .get() for attributes, including namespaced ones like 'xlink:href'
            href = loc.get('{' + self.ns['xlink'] + '}href')
            label = loc.get('{' + self.ns['xlink'] + '}label')
            if href and '#' in href:
                # The href contains the file path, we just want the concept ID
                concept = href.split('#')[-1]  # "us-gaap_Assets"
                loc_to_concept[label] = concept

        # 2. Map <label> 'label' (e.g., "lab_1") to its text (e.g., "Assets")
        label_to_text = {}
        for label in root_lab.iter('{' + self.ns['link'] + '}label'):
            role = label.get('{' + self.ns['xlink'] + '}role')
            label_id = label.get('{' + self.ns['xlink'] + '}label')
            
            # We only want the standard human-readable label.
            # XBRL has other roles like "verboseLabel", "documentation", etc.
            if role == 'http://www.xbrl.org/2003/role/label':
                label_to_text[label_id] = label.text

        # 3. Connect them using <labelArc>
        # This arc maps "from" a <loc> "to" a <label>
        for arc in root_lab.iter('{' + self.ns['link'] + '}labelArc'):
            arc_from = arc.get('{' + self.ns['xlink'] + '}from') # e.g., "loc_1"
            arc_to = arc.get('{' + self.ns['xlink'] + '}to')     # e.g., "lab_1"
            
            # Resolve the pointers from the maps built in steps 1 & 2
            concept = loc_to_concept.get(arc_from)
            text = label_to_text.get(arc_to)
            
            if concept and text:
                # Populate both of our indexes for fast O(1) lookups
                self.label_to_concept[text.lower()] = concept
                self.concept_to_label[concept] = text
                
        print(f"  [LabelParser] Index built. {len(self.concept_to_label)} concepts loaded.")

    def find_concepts_by_query(self, query):
        """
        Returns a list of concept names that match the query words.
        This provides a robust "AND" search (e.g., "earnings per share").
        """

        # Split the query into words for a more robust "AND" search
        query_words = query.lower().split()
        concepts_found = []

        for label_text_lower, concept in self.label_to_concept.items():
            # Check if all query words are in the label
            # This is an O(N*M) operation (N labels, M query words)
            # but is fast in practice for small M.
            if all(word in label_text_lower for word in query_words):
                concepts_found.append(concept)

        return concepts_found

    def get_label_for_concept(self, concept):
        """Helper to get a clean label for a CSV row."""
        # Fallback to the concept name itself if no label was found
        return self.concept_to_label.get(concept, concept)
