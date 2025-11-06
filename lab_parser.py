import xml.etree.ElementTree as ET


class LabelParser:
    """
    Parses the _lab.xml file.
    Its job is to build a two-way index to find concepts by their
    human-readable labels.
    """

    def __init__(self, lab_path, namespaces):
        print(f"  [LabelParser] Initializing and building index from {lab_path.name}...")
        self.ns = namespaces  # Get namespaces from orchestrator
        self.label_to_concept = {}  # Search index (label -> concept)
        self.concept_to_label = {}  # Lookup index (concept -> label)

        tree_lab = ET.parse(lab_path)
        root_lab = tree_lab.getroot()

        # 1. Map loc 'label' to concept 'href'
        loc_to_concept = {}
        for loc in root_lab.iter('{' + self.ns['link'] + '}loc'):
            href = loc.get('{' + self.ns['xlink'] + '}href')
            label = loc.get('{' + self.ns['xlink'] + '}label')
            if href and '#' in href:
                concept = href.split('#')[-1]  # "us-gaap_Assets"
                loc_to_concept[label] = concept

        # 2. Map label 'label' to label text
        label_to_text = {}
        for label in root_lab.iter('{' + self.ns['link'] + '}label'):
            role = label.get('{' + self.ns['xlink'] + '}role')
            label_id = label.get('{' + self.ns['xlink'] + '}label')
            if role == 'http://www.xbrl.org/2003/role/label':
                label_to_text[label_id] = label.text

        # 3. Connect them using <labelArc>
        for arc in root_lab.iter('{' + self.ns['link'] + '}labelArc'):
            arc_from = arc.get('{' + self.ns['xlink'] + '}from')
            arc_to = arc.get('{' + self.ns['xlink'] + '}to')
            concept = loc_to_concept.get(arc_from)
            text = label_to_text.get(arc_to)
            if concept and text:
                self.label_to_concept[text.lower()] = concept
                self.concept_to_label[concept] = text
        print(f"  [LabelParser] Index built. {len(self.concept_to_label)} concepts loaded.")

    def find_concepts_by_query(self, query):
        """Returns a list of concept names that match the query."""

        # --- THIS IS THE FIX ---
        # Split the query into words for a more robust "AND" search
        query_words = query.lower().split()
        concepts_found = []

        for label_text_lower, concept in self.label_to_concept.items():
            # Check if all query words are in the label
            if all(word in label_text_lower for word in query_words):
                concepts_found.append(concept)
        # --- END OF FIX ---

        return concepts_found

    def get_label_for_concept(self, concept):
        """Helper to get a clean label for a CSV row."""
        return self.concept_to_label.get(concept, concept)
