# ADP Batch Scraper - Process Flow

```
┌─────────────────────────┐
│   1. Read Excel file    │
└───────────┬─────────────┘
            │
            ▼
┌─────────────────────────┐
│ 2. Create output folder │
└───────────┬─────────────┘
            │
            ▼
┌─────────────────────────┐
│   3. Navigate to URL    │
└───────────┬─────────────┘
            │
            ▼
┌─────────────────────────┐
│   4. Handle popups      │
└───────────┬─────────────┘
            │
            ▼
┌─────────────────────────┐
│   5. Scroll page        │
└───────────┬─────────────┘
            │
            ▼
┌─────────────────────────┐
│   6. Expand content     │
└───────────┬─────────────┘
            │
            ▼
┌─────────────────────────┐
│ 7. Capture screenshots  │
└───────────┬─────────────┘
            │
            ▼
┌─────────────────────────┐
│   8. Extract data       │
└───────────┬─────────────┘
            │
            ▼
┌─────────────────────────┐
│  9. Download images     │
└───────────┬─────────────┘
            │
            ▼
┌─────────────────────────┐
│    10. Save files       │
└───────────┬─────────────┘
            │
            ▼
┌─────────────────────────┐
│  11. Generate report    │
└─────────────────────────┘
```

---

## Step Descriptions

**1. Read Excel file**  
Loads the Excel workbook and extracts the `Data Segment` and `Data Sources` columns containing category labels and target URLs.

**2. Create output folder**  
Creates a structured folder for each URL: `DOMFolder/{Segment}__{page-name}/` with subfolders for images and screenshots.

**3. Navigate to URL**  
Opens the page in a headless Chromium browser and waits for network activity to settle, ensuring initial content is loaded.

**4. Handle popups**  
Dismisses cookie banners, employee count selection modals, chat widgets, and other overlay elements that may block content.

**5. Scroll page**  
Scrolls through the entire page multiple times to trigger lazy-loaded images and dynamically loaded content.

**6. Expand content**  
Clicks on navigation tabs and expands accordion/FAQ sections to reveal all hidden content on the page.

**7. Capture screenshots**  
Takes viewport screenshots while scrolling, then stitches them into a compressed full-page image (JPEG format for smaller file size).

**8. Extract data**  
Parses the DOM to extract all image sources (including lazy-load attributes) and hyperlinks with their text and metadata.

**9. Download images**  
Downloads all extracted images to the `/images` subfolder with hashed filenames and tracks success/failure status.

**10. Save files**  
Saves the complete HTML DOM and a JSON mapping file containing images, links, and extraction metadata.

**11. Generate report**  
Creates a `batch_report.json` summarizing all processed URLs with success/failure counts and detailed results per page.
