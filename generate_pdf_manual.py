#!/usr/bin/env python3
import sys
import re
from pathlib import Path
from fpdf import FPDF

# Custom PDF class with styling
class JASCManualPDF(FPDF):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.chapter_title = ""
        # Register a page numbering alias
        self.alias_nb_pages()
        
    def header(self):
        # Skip header on cover page (page 1) and TOC page (page 2)
        if self.page_no() <= 2:
            return
            
        self.set_font("Helvetica", "I", 8)
        self.set_text_color(140, 150, 160)
        # Left header: Document title
        self.cell(0, 10, "JASC Data Processor - User Manual", align="L")
        self.set_x(20) # Reset x
        # Right header: Current chapter
        if self.chapter_title:
            self.cell(0, 10, self.chapter_title, align="R")
        
        # Underline
        self.set_draw_color(200, 210, 220)
        self.set_line_width(0.2)
        self.line(20, 22, 195, 22)
        self.ln(12)

    def footer(self):
        # Skip footer on cover page (page 1)
        if self.page_no() == 1:
            return
            
        self.set_y(-15)
        self.set_font("Helvetica", "I", 8)
        self.set_text_color(140, 150, 160)
        
        # Thin divider line
        self.set_draw_color(220, 225, 230)
        self.set_line_width(0.2)
        self.line(20, self.h - 18, 195, self.h - 18)
        
        # Left footer: Version / Copyright
        self.cell(0, 10, "Version 0.1.0 | GPL-3.0 License", align="L")
        self.set_x(20)
        # Right footer: Page number
        self.cell(0, 10, f"Page {self.page_no()} of {{nb}}", align="R")


def parse_inline_styles(pdf, text, line_height=5):
    """
    Renders text inline, handling bold (**text**) and code (`code`).
    Does not print newline at the end.
    """
    # Regex to extract bold and code segments
    # Pattern matches either **bold**, `code` or normal text
    pattern = re.compile(r"(\*\*[^*]+\*\*|`[^`]+`)")
    parts = pattern.split(text)
    
    for part in parts:
        if part.startswith("**") and part.endswith("**"):
            # Bold text
            pdf.set_font("Helvetica", "B", pdf.font_size_pt)
            pdf.set_text_color(15, 32, 66) # Deep Navy
            content = part[2:-2]
        elif part.startswith("`") and part.endswith("`"):
            # Code inline
            pdf.set_font("Courier", "B", pdf.font_size_pt - 0.5)
            pdf.set_text_color(199, 37, 78) # Crimson Red
            content = f" {part[1:-1]} "
        else:
            # Normal text
            pdf.set_font("Helvetica", "", pdf.font_size_pt)
            pdf.set_text_color(38, 55, 71) # Charcoal
            content = part
            
        pdf.write(line_height, content)


def render_pdf_manual():
    workspace_dir = Path(__file__).parent
    md_file = workspace_dir / "JASC_Manual.md"
    pdf_file = workspace_dir / "JASC_Manual.pdf"
    logo_file = workspace_dir / "resources" / "logo.png"
    
    if not md_file.exists():
        print(f"Error: {md_file} not found!")
        sys.exit(1)
        
    print("Reading JASC_Manual.md...")
    with open(md_file, "r", encoding="utf-8") as f:
        lines = f.readlines()
        
    # First pass: Extract sections for TOC and chapter page tracking
    toc_entries = []
    current_h2 = ""
    
    # Initialize PDF
    # Page size: Letter (8.5 x 11 inches)
    # Unit: mm (215.9 x 279.4 mm)
    pdf = JASCManualPDF(orientation="P", unit="mm", format="letter")
    pdf.set_margins(20, 20, 20)
    pdf.set_auto_page_break(True, margin=20)
    
    # ==========================================
    # COVER PAGE
    # ==========================================
    pdf.add_page()
    
    # Decorative header block (navy bar)
    pdf.set_fill_color(15, 32, 66) # Deep Navy
    pdf.rect(0, 0, 215.9, 15, "F")
    
    # Logo
    if logo_file.exists():
        pdf.image(str(logo_file), x=85, y=40, w=45)
    else:
        print("Warning: Logo not found, skipping cover image.")
        pdf.ln(35)
        
    pdf.set_y(100)
    pdf.set_font("Helvetica", "B", 30)
    pdf.set_text_color(15, 32, 66)
    pdf.cell(0, 15, "JASC DATA PROCESSOR", align="C", new_x="LMARGIN", new_y="NEXT")
    
    pdf.set_font("Helvetica", "B", 18)
    pdf.set_text_color(47, 119, 188) # Slate Blue
    pdf.cell(0, 10, "Comprehensive User Manual", align="C", new_x="LMARGIN", new_y="NEXT")
    
    # Accent separator line
    pdf.set_draw_color(47, 119, 188)
    pdf.set_line_width(1.5)
    pdf.line(65, 130, 150, 130)
    
    pdf.set_y(140)
    pdf.set_font("Helvetica", "", 11)
    pdf.set_text_color(38, 55, 71)
    pdf.multi_cell(0, 6, "A lightweight, modular desktop application for data ingestion, visualization,\nmathematical transforms, statistics, and curve fitting.", align="C")
    
    # Metadata footer on cover page
    pdf.set_y(230)
    pdf.set_font("Helvetica", "B", 10)
    pdf.set_text_color(15, 32, 66)
    pdf.cell(0, 5, "Reference Manual & Guide", align="C", new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("Helvetica", "", 9)
    pdf.set_text_color(100, 110, 120)
    pdf.cell(0, 5, "Version 0.1.0 (Stable release)", align="C", new_x="LMARGIN", new_y="NEXT")
    pdf.cell(0, 5, "Compiled: June 2026", align="C", new_x="LMARGIN", new_y="NEXT")
    pdf.cell(0, 5, "License: GNU General Public License v3.0", align="C", new_x="LMARGIN", new_y="NEXT")
    
    # ==========================================
    # TABLE OF CONTENTS (PAGE 2 Placeholder)
    # ==========================================
    pdf.add_page()
    # We will write the actual content of Page 2 later, once we know the page numbers of each section!
    
    # ==========================================
    # PARSING AND RENDERING SECTIONS (PASS 2)
    # ==========================================
    in_code_block = False
    code_lines = []
    
    in_table = False
    table_rows = []
    
    in_callout = False
    callout_type = "NOTE" # NOTE, WARNING, IMPORTANT
    callout_lines = []
    
    in_list = False
    
    # Skip lines until after the Table of Contents header in the markdown
    skip_mode = True
    
    for line in lines:
        stripped = line.strip()
        
        # Check when to end skip mode
        if skip_mode:
            if stripped.startswith("## 1."):
                skip_mode = False
            else:
                continue
                
        # Handle Code Blocks
        if stripped.startswith("```"):
            if in_code_block:
                # End of code block, render it
                in_code_block = False
                pdf.set_font("Courier", "", 8.5)
                pdf.set_fill_color(237, 242, 247) # Light gray
                pdf.set_draw_color(200, 210, 220)
                pdf.set_text_color(38, 55, 71)
                
                code_text = "\n".join(code_lines)
                
                # Check height of code block to handle page breaks cleanly
                num_lines = len(code_lines)
                estimated_height = num_lines * 4 + 6
                if pdf.get_y() + estimated_height > pdf.page_break_trigger:
                    pdf.add_page()
                    
                pdf.multi_cell(0, 4.2, code_text, border=1, fill=True, align="L")
                pdf.ln(4)
                code_lines = []
            else:
                in_code_block = True
            continue
            
        if in_code_block:
            # Add line to code lines block (preserving spaces)
            code_lines.append(line.replace("\n", ""))
            continue
            
        # Handle Tables
        if stripped.startswith("|"):
            in_table = True
            # Parse table row
            cells = [c.strip() for c in stripped.split("|")[1:-1]]
            # If it's a separator row (e.g. |---|---|), skip it
            if all(all(char == '-' for char in cell) or cell == '' for cell in cells):
                continue
            table_rows.append(cells)
            continue
        elif in_table:
            # End of table, render accumulated rows
            in_table = False
            if table_rows:
                pdf.set_font("Helvetica", "", 9)
                
                # Simple width allocation: divide evenly or customize
                num_cols = len(table_rows[0])
                col_width = (215.9 - 40) / num_cols # Printable width (175.9) / num_cols
                
                # Draw header row
                pdf.set_font("Helvetica", "B", 9)
                pdf.set_fill_color(47, 119, 188) # Slate Blue
                pdf.set_draw_color(200, 210, 220)
                pdf.set_text_color(255, 255, 255)
                for cell in table_rows[0]:
                    pdf.cell(col_width, 8, cell, border=1, fill=True, align="C")
                pdf.ln()
                
                # Draw data rows
                pdf.set_font("Helvetica", "", 8.5)
                pdf.set_text_color(38, 55, 71)
                zebra = False
                for row_idx, row in enumerate(table_rows[1:]):
                    # Check height and add page if needed
                    if pdf.get_y() + 8 > pdf.page_break_trigger:
                        pdf.add_page()
                        # Redraw header
                        pdf.set_font("Helvetica", "B", 9)
                        pdf.set_fill_color(47, 119, 188)
                        pdf.set_text_color(255, 255, 255)
                        for cell in table_rows[0]:
                            pdf.cell(col_width, 8, cell, border=1, fill=True, align="C")
                        pdf.ln()
                        pdf.set_font("Helvetica", "", 8.5)
                        pdf.set_text_color(38, 55, 71)
                    
                    pdf.set_fill_color(244, 247, 250)
                    for col_idx, cell in enumerate(row):
                        pdf.cell(col_width, 8, cell, border=1, fill=zebra, align="L")
                    pdf.ln()
                    zebra = not zebra
                pdf.ln(4)
                table_rows = []
            # Fall through or continue depending on current line
            
        # Handle Callout Boxes (Note / Warning / Important)
        if stripped.startswith(">"):
            # Check type of callout
            if "[!WARNING]" in stripped:
                in_callout = True
                callout_type = "WARNING"
                continue
            elif "[!NOTE]" in stripped:
                in_callout = True
                callout_type = "NOTE"
                continue
            elif "[!IMPORTANT]" in stripped:
                in_callout = True
                callout_type = "IMPORTANT"
                continue
            elif in_callout:
                # Strip leading '>' and spaces
                call_text = stripped[1:].strip()
                callout_lines.append(call_text)
                continue
        elif in_callout:
            # End of callout, render it
            in_callout = False
            
            # Setup colors
            if callout_type == "WARNING":
                fill_color = (255, 248, 230) # Light orange/yellow
                border_color = (226, 135, 67) # Warning Orange
                title_text = "WARNING"
            elif callout_type == "IMPORTANT":
                fill_color = (255, 235, 235) # Light red
                border_color = (220, 53, 69) # Red
                title_text = "IMPORTANT"
            else: # NOTE
                fill_color = (235, 243, 255) # Light blue
                border_color = (47, 119, 188) # Slate Blue
                title_text = "NOTE"
                
            pdf.set_fill_color(*fill_color)
            pdf.set_draw_color(*border_color)
            pdf.set_text_color(*border_color)
            
            content_text = " ".join(callout_lines)
            
            # Estimate height for callout
            pdf.set_font("Helvetica", "B", 9)
            title_w = pdf.get_string_width(f"[{title_text}]  ")
            pdf.set_font("Helvetica", "I", 9.5)
            inner_w = 215.9 - 40 - 10
            lines_needed = pdf.multi_cell(inner_w, 4.5, content_text, dry_run=True, output="LINES")
            estimated_height = len(lines_needed) * 4.5 + 8
            
            if pdf.get_y() + estimated_height > pdf.page_break_trigger:
                pdf.add_page()
                
            # Draw box using rect and cell
            x_start = pdf.get_x()
            y_start = pdf.get_y()
            
            # Draw colored background rectangle
            pdf.rect(x_start, y_start, 215.9 - 40, estimated_height, "F")
            
            # Draw thick left border
            pdf.set_fill_color(*border_color)
            pdf.rect(x_start, y_start, 1.5, estimated_height, "F")
            
            # Write title & content
            pdf.set_y(y_start + 4)
            pdf.set_x(x_start + 5)
            pdf.set_font("Helvetica", "B", 9)
            pdf.write(4.5, f"[{title_text}]  ")
            
            pdf.set_font("Helvetica", "I", 9.5)
            pdf.set_text_color(38, 55, 71)
            parse_inline_styles(pdf, content_text, line_height=4.5)
            
            pdf.set_y(y_start + estimated_height)
            pdf.ln(5)
            callout_lines = []
            # Note: We don't skip the current line since it is the one that triggered the end of the callout
            
        # Handle Headings
        if stripped.startswith("#"):
            # Check depth
            depth = 0
            while depth < len(stripped) and stripped[depth] == '#':
                depth += 1
                
            header_text = stripped[depth:].strip()
            
            if depth == 1:
                # Main document title (we already have a cover page, but let's handle if it occurs)
                pdf.ln(5)
                pdf.set_font("Helvetica", "B", 22)
                pdf.set_text_color(15, 32, 66)
                pdf.cell(0, 12, header_text, new_x="LMARGIN", new_y="NEXT", align="L")
                pdf.ln(5)
            elif depth == 2:
                # Chapter Heading (e.g. ## 1. Installation)
                # We start each major chapter on a new page to look clean!
                pdf.add_page()
                current_h2 = header_text
                pdf.chapter_title = header_text
                
                # Keep track of TOC entries (Header text, page number)
                toc_entries.append((header_text, pdf.page_no(), 2))
                
                pdf.ln(2)
                pdf.set_font("Helvetica", "B", 16)
                pdf.set_text_color(15, 32, 66)
                pdf.cell(0, 10, header_text, new_x="LMARGIN", new_y="NEXT", align="L")
                
                # Accent bar underneath the chapter title
                pdf.set_fill_color(47, 119, 188)
                pdf.rect(20, pdf.get_y() + 1, 60, 2.5, "F")
                pdf.ln(8)
            elif depth == 3:
                # Subsection Heading (e.g. ### CSV/TXT Import)
                pdf.ln(4)
                toc_entries.append((header_text, pdf.page_no(), 3))
                
                # Check height before printing H3
                if pdf.get_y() + 15 > pdf.page_break_trigger:
                    pdf.add_page()
                    
                pdf.set_font("Helvetica", "B", 12)
                pdf.set_text_color(47, 119, 188)
                pdf.cell(0, 8, header_text, new_x="LMARGIN", new_y="NEXT", align="L")
                pdf.ln(2)
            continue
            
        # Skip empty lines
        if not stripped:
            if not in_list:
                pdf.ln(3)
            continue
            
        # Handle lists
        is_bullet = stripped.startswith("* ") or stripped.startswith("- ")
        is_numbered = re.match(r"^\d+\.\s+", stripped) is not None
        
        if is_bullet or is_numbered:
            in_list = True
            indent = 8
            
            # Draw list indicator
            pdf.set_x(20 + indent)
            pdf.set_font("Helvetica", "B", 10)
            pdf.set_text_color(47, 119, 188) # Slate Blue
            
            if is_bullet:
                marker = chr(149) # Bullet point
                content = stripped[2:]
                pdf.cell(4, 5.5, marker, align="L")
            else:
                match = re.match(r"^(\d+\.)\s+", stripped)
                marker = match.group(1)
                content = stripped[len(match.group(0)):]
                pdf.cell(6, 5.5, marker, align="L")
                
            pdf.set_font("Helvetica", "", 10)
            pdf.set_text_color(38, 55, 71)
            
            # Print list content with inline style support
            parse_inline_styles(pdf, content, line_height=5.5)
            pdf.ln(5.5)
        else:
            in_list = False
            # Standard Paragraph
            pdf.set_font("Helvetica", "", 10)
            pdf.set_text_color(38, 55, 71)
            
            # Indent slightly if it's text art / layout diagram (checking if it starts with special lines or has spaces)
            if stripped.startswith("+----") or stripped.startswith("|  "):
                pdf.set_font("Courier", "", 8)
                pdf.set_fill_color(248, 250, 252)
                # Simple box border around diagram
                pdf.cell(0, 4, line.replace("\n", ""), new_x="LMARGIN", new_y="NEXT", fill=True)
            else:
                # Wrap long paragraphs properly using cell wrapping
                parse_inline_styles(pdf, stripped, line_height=5.2)
                pdf.ln(5.2)
                
    # ==========================================
    # WRITE TABLE OF CONTENTS (PAGE 2 CONTENT)
    # ==========================================
    # Go back to page 2 (Table of Contents page)
    pdf.page = 2
    
    pdf.set_y(25)
    pdf.set_font("Helvetica", "B", 20)
    pdf.set_text_color(15, 32, 66)
    pdf.cell(0, 10, "Table of Contents", new_x="LMARGIN", new_y="NEXT", align="L")
    
    pdf.set_fill_color(47, 119, 188)
    pdf.rect(20, pdf.get_y() + 1, 40, 1.5, "F")
    pdf.ln(8)
    
    # Write TOC entries
    for entry, page_num, depth in toc_entries:
        # We only list level 2 (Chapters) and level 3 (Subsections)
        if depth == 2:
            pdf.set_font("Helvetica", "B", 10.5)
            pdf.set_text_color(15, 32, 66)
            indent = ""
            dot_color = (200, 210, 220)
        else: # level 3
            pdf.set_font("Helvetica", "", 9.5)
            pdf.set_text_color(38, 55, 71)
            indent = "    "
            dot_color = (230, 235, 240)
            
        full_entry = f"{indent}{entry}"
        entry_width = pdf.get_string_width(full_entry)
        page_str = str(page_num)
        page_width = pdf.get_string_width(page_str)
        
        # Draw dot leaders
        dot_leader = ""
        # Printable width (175.9) minus margins
        dots_width_target = 175.9 - entry_width - page_width - 2
        
        pdf.write(5.5, full_entry)
        
        # Calculate dots
        pdf.set_text_color(*dot_color)
        pdf.set_font("Helvetica", "", 9)
        dot_char_width = pdf.get_string_width(".")
        num_dots = int(dots_width_target / dot_char_width) - 2
        dot_leader = "." * num_dots
        
        pdf.write(5.5, f" {dot_leader} ")
        
        # Restore text color for page number
        if depth == 2:
            pdf.set_font("Helvetica", "B", 10.5)
            pdf.set_text_color(15, 32, 66)
        else:
            pdf.set_font("Helvetica", "", 9.5)
            pdf.set_text_color(38, 55, 71)
            
        pdf.cell(0, 5.5, page_str, align="R", new_x="LMARGIN", new_y="NEXT")
        pdf.ln(1)
        
    print(f"Saving PDF to {pdf_file}...")
    pdf.output(str(pdf_file))
    print("PDF compilation completed successfully!")


if __name__ == "__main__":
    render_pdf_manual()
