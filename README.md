# XBRL Statement Parser

## Overview

This project is a high-performance Python parser for extracting structured financial statements from SEC EDGAR XBRL filings.

It is designed to deconstruct the complex, relationship-based XBRL files (`_lab.xml`, `_pre.xml`, `_htm.xml`) into clean, human-readable CSVs. Instead of just dumping raw data, it intelligently reconstructs entire financial statements (like the Income Statement or Balance Sheet) in their correct presentation order.

## Key Features

* **Statement Reconstruction:** Accurately rebuilds financial statements by parsing the Presentation Linkbase (`_pre.xml`).
* **Orchestrator Pattern:** Uses an `XbrlParser` (in `main.py`) to orchestrate "worker" parsers (`HtmParser`, `LabelParser`, `PresentationParser`), each with a distinct responsibility.
* **Intelligent Contexts:** Automatically finds the most recent "instant" (for Balance Sheets) or "duration" (for Income Statements) time periods.
* **Dynamic Namespace Resolution:** Automatically discovers and resolves all XML namespaces, making the parser robust against different company-specific filings.
* **High-Precision Scaling:** Correctly handles all XBRL scaling (e.g., `scale="6"`, `decimals="-3"`) using `Decimal` arithmetic to avoid floating-point errors with large financial figures.
* **Flexible Queries:** Can extract entire statements (`'income statement'`) or specific line items (`'Goodwill'`) from the same query engine.

## How It Works

The parser's architecture is built on a main **Orchestrator** and several **Workers**:

1.  **`XbrlParser` (The Orchestrator):**
    * Located in `main.py`, this is the public-facing class.
    * It infers all required file paths from a single `_htm.xml` file.
    * It discovers all XML namespaces and injects them as dependencies into the worker parsers.
    * It coordinates the entire workflow: finding concepts, finding contexts, fetching data, and writing the CSV.

2.  **`LabelParser` (The "Dictionary"):**
    * Parses the `_lab.xml` file.
    * Builds a high-speed, two-way hash map (`dict`) to look up a concept's name from its label (e.g., `"Revenues"` -> `"us-gaap:Revenues"`) and vice-versa.

3.  **`PresentationParser` (The "Map"):**
    * Parses the `_pre.xml` file.
    * Its job is to find the *order* of a statement. It builds a graph (tree) of relationships and uses a Depth-First Search (DFS) to return the exact ordered list of concepts for a given statement.

4.  **`HtmParser` (The "Database"):**
    * Parses the main `_htm.xml` instance file.
    * It loads all contexts (time periods) and all financial values (facts) into memory.
    * This class is responsible for storing the *full* value object, including scaling attributes (`scale`, `decimals`), so that the final numbers can be calculated accurately.

## Usage

The primary entry point is the `if __name__ == "__main__":` block in `main.py`.

1.  **Set Your File:**
    Change the `HTM_FILE_PATH` variable to point to the `_htm.xml` file you want to parse. The parser requires the file to be in a directory structure like `.../TICKER/PERIOD/filename.xml` so it can auto-name the output folder.

    ```python
    # Example for Meta:
    HTM_FILE_PATH = 'meta/Q2/meta-20250331_htm.xml'
    ```

2.  **Define Your Queries:**
    Add or remove strings from the `queries_to_run` list. The parser will attempt to find a matching statement *or* a matching label.

    ```python
    queries_to_run = [
        'income statement',
        'balance sheet',
        'earnings per share',
        'cash flow',
        'Goodwill'
    ]
    ```

3.  **Run the Script:**
    ```bash
    python main.py
    ```

4.  **Check Your Output:**
    The script will create a new folder (e.g., `financial_statements_META_20250331`) containing the resulting CSV files.

## Dependencies

* **Python 3.9+**
* **No external libraries** (beyond the standard `xml`, `decimal`, `pathlib`, etc.)
