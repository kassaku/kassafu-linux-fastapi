#!/usr/bin/env python3
"""
LOC (Lines of Code) analyzer that scans a directory archive and generates
a timeline graph from 2010 to 2026.

Copyright (c) 2026 Houkes Horeca Applications

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
"""

import os
import sys
from pathlib import Path
from datetime import datetime
from collections import defaultdict
import argparse
from typing import Dict, Tuple, List

# Try to import matplotlib, provide helpful error if missing
try:
    import matplotlib.pyplot as plt
    import matplotlib.dates as mdates
    from matplotlib.ticker import MultipleLocator
except ImportError:
    print("[108051] Error: matplotlib is required. Install with: pip install matplotlib")
    sys.exit(1)

# File extensions to count as code (expand as needed)
CODE_EXTENSIONS = {
    '.py', '.js', '.ts', '.jsx', '.tsx', '.java', '.c', '.cpp', '.h', '.hpp',
    '.cs', '.go', '.rs', '.rb', '.php', '.swift', '.kt', '.kts', '.scala',
    '.html', '.css', '.scss', '.sass', '.less', '.vue', '.svelte',
    '.sql', '.sh', '.bash', '.zsh', '.ps1', '.pl', '.lua', '.r',
    '.json', '.xml', '.yaml', '.yml', '.toml', '.ini', '.cfg',
    '.md', '.rst', '.txt',  # Documentation (optional)
}

# Extensions to exclude
EXCLUDE_DIRS = {
    '__pycache__', '.git', '.svn', '.hg', 'node_modules', 'venv', 
    'env', '.venv', '.env', 'dist', 'build', 'target', '.idea', 
    '.vscode', '.vs', 'bin', 'obj', 'lib', 'libs', 'deps'
}

EXCLUDE_FILES = {
    '.DS_Store', 'Thumbs.db', 'desktop.ini'
}

def count_loc(file_path: Path) -> int:
    """Count non-empty, non-comment lines in a file (simple version)."""
    try:
        with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
            lines = f.readlines()
    except Exception:
        return 0
    
    loc = 0
    in_multiline_comment = False
    
    for line in lines:
        stripped = line.strip()
        
        # Skip empty lines
        if not stripped:
            continue
        
        # Simple multiline comment detection (for /* */ style)
        if '/*' in stripped and '*/' not in stripped:
            in_multiline_comment = True
            continue
        if in_multiline_comment:
            if '*/' in stripped:
                in_multiline_comment = False
            continue
        
        # Skip single-line comments (add more patterns as needed)
        if stripped.startswith('//') or stripped.startswith('#') or stripped.startswith('--'):
            continue
        
        loc += 1
    
    return loc

def get_file_year(file_path: Path) -> int:
    """Get the year from file's modification time."""
    try:
        mtime = os.path.getmtime(file_path)
        return datetime.fromtimestamp(mtime).year
    except Exception:
        return None

def scan_archive(archive_path: Path, verbose: bool = False) -> Dict[int, int]:
    """Scan archive and return dict of year -> total LOC."""
    loc_by_year = defaultdict(int)
    file_count_by_year = defaultdict(int)
    total_files = 0
    total_loc = 0
    
    if not archive_path.exists():
        print(f"[108051] Error: Path '{archive_path}' does not exist.")
        return {}
    
    print(f"[0] Scanning: {archive_path}")
    print(f"[0] This may take a while for large archives...\n")
    
    for root, dirs, files in os.walk(archive_path):
        # Filter out excluded directories
        dirs[:] = [d for d in dirs if d not in EXCLUDE_DIRS]
        
        for file in files:
            if file in EXCLUDE_FILES:
                continue
            
            file_path = Path(root) / file
            ext = file_path.suffix.lower()
            
            if ext not in CODE_EXTENSIONS:
                continue
            
            year = get_file_year(file_path)
            if year is None or year < 2010 or year > 2026:
                continue
            
            loc = count_loc(file_path)
            if loc > 0:  # Only count files with actual code
                loc_by_year[year] += loc
                file_count_by_year[year] += 1
                total_loc += loc
                total_files += 1
    
    print(f"[0] Scan complete!")
    print(f"  Total files analyzed: {total_files:,}")
    print(f"  Total lines of code: {total_loc:,}")
    print(f"  Years covered: {min(loc_by_year.keys()) if loc_by_year else 'N/A'} - {max(loc_by_year.keys()) if loc_by_year else 'N/A'}\n")
    
    if verbose:
        print("[0] Breakdown by year:")
        for year in sorted(loc_by_year.keys()):
            print(f"  {year}: {loc_by_year[year]:,} LOC ({file_count_by_year[year]} files)")
        print()
    
    return loc_by_year

def generate_graph(loc_by_year: Dict[int, int], output_file: str = "loc_timeline.png"):
    """Generate a beautiful timeline graph."""
    if not loc_by_year:
        print("[108051] No data to graph. Please check your archive path.")
        return
    
    years = sorted(loc_by_year.keys())
    loc_values = [loc_by_year[year] for year in years]
    
    # Create figure with a clean, modern style
    plt.style.use('seaborn-v0_8-darkgrid')
    fig, ax = plt.subplots(figsize=(14, 8))
    
    # Bar chart with gradient-like colors (darker green for more recent years)
    colors = plt.cm.YlGn(np.linspace(0.4, 0.9, len(years)))
    bars = ax.bar(years, loc_values, color=colors, edgecolor='darkgreen', linewidth=1.5, alpha=0.85)
    
    # Add value labels on top of bars
    for bar, loc in zip(bars, loc_values):
        height = bar.get_height()
        ax.text(bar.get_x() + bar.get_width()/2., height + max(loc_values)*0.01,
                f'{loc:,}', ha='center', va='bottom', fontsize=9, fontweight='bold')
    
    # Add cumulative line
    cumulative = np.cumsum(loc_values)
    ax2 = ax.twinx()
    line = ax2.plot(years, cumulative, color='darkred', marker='o', linewidth=2.5, 
                    markersize=8, label='Cumulative LOC', zorder=5)
    ax2.set_ylabel('Cumulative Lines of Code', fontsize=11, color='darkred')
    ax2.tick_params(axis='y', labelcolor='darkred')
    
    # Format x-axis (years)
    ax.set_xticks(range(2010, 2027, 2))
    ax.set_xlim(2009.5, 2026.5)
    ax.set_xlabel('Year', fontsize=12, fontweight='bold')
    
    # Format y-axis
    ax.set_ylabel('Lines of Code per Year', fontsize=12, fontweight='bold')
    ax.yaxis.set_major_formatter(plt.FuncFormatter(lambda x, p: f'{int(x):,}'))
    
    # Title and subtitles
    total_loc = sum(loc_values)
    start_year = min(years)
    avg_loc = total_loc // len(years)
    growth = loc_values[-1] - loc_values[0] if len(loc_values) > 1 else 0
    
    title = f'📊 Code Evolution Timeline: {start_year} - 2026'
    subtitle = f'Total: {total_loc:,} LOC | Peak: {max(loc_values):,} ({years[loc_values.index(max(loc_values))]}) | Growth: {growth:+,} LOC'
    
    ax.set_title(title, fontsize=16, fontweight='bold', pad=20)
    ax.text(0.5, 0.98, subtitle, transform=ax.transAxes, fontsize=10, 
            ha='center', va='top', style='italic', color='gray')
    
    # Add grid for better readability
    ax.grid(True, alpha=0.3, linestyle='--', linewidth=0.5)
    ax.set_axisbelow(True)
    
    # Legend
    from matplotlib.patches import Patch
    legend_elements = [Patch(facecolor=colors[-1], edgecolor='darkgreen', label='LOC per year'),
                      plt.Line2D([0], [0], color='darkred', marker='o', linewidth=2.5, 
                                markersize=6, label='Cumulative total')]
    ax.legend(handles=legend_elements, loc='upper left', framealpha=0.9, fontsize=10)
    
    # Adjust layout and save
    plt.tight_layout()
    plt.savefig(output_file, dpi=150, bbox_inches='tight')
    print(f"✅ [0] Graph saved as: {output_file}")
    
    # Also show the plot if running interactively
    if sys.stdout.isatty():  # Only show if running in terminal interactively
        plt.show()

def main():
    parser = argparse.ArgumentParser(
        description='Generate a graph showing lines of code in your archive (2010-2026)'
    )
    parser.add_argument('archive_path', type=str, 
                       help='Path to your archive directory')
    parser.add_argument('-o', '--output', type=str, default='loc_timeline.png',
                       help='Output filename for the graph (default: loc_timeline.png)')
    parser.add_argument('-v', '--verbose', action='store_true',
                       help='Show detailed year-by-year breakdown')
    parser.add_argument('-e', '--extensions', type=str, nargs='+',
                       help='Additional file extensions to include (e.g., .cpp .h)')
    
    args = parser.parse_args()
    
    # Add any extra extensions from command line
    if args.extensions:
        for ext in args.extensions:
            if not ext.startswith('.'):
                ext = '.' + ext
            CODE_EXTENSIONS.add(ext.lower())
    
    # Scan the archive
    archive_path = Path(args.archive_path).expanduser().resolve()
    loc_by_year = scan_archive(archive_path, args.verbose)
    
    if loc_by_year:
        generate_graph(loc_by_year, args.output)
    else:
        print("[108051] ❌ No code files found in the specified date range (2010-2026).")
        print("   Tips:")
        print("   - Make sure your archive path is correct")
        print("   - Files need modification dates between 2010-2026")
        print("   - Use -e to add more file extensions if needed")

if __name__ == "__main__":
    import numpy as np  # Import here since we need it for cumulative
    main()

