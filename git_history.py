#!/usr/bin/env python3
"""
LOC (Lines of Code) analyzer that uses git history for accurate timeline data.
Works with both git repositories and regular directories.
"""

import os
import sys
import subprocess
from pathlib import Path
from datetime import datetime
from collections import defaultdict
import argparse
from typing import Dict, List, Optional

# Try to import required libraries
try:
    import matplotlib.pyplot as plt
    import numpy as np
except ImportError:
    print("[108051] Error: matplotlib and numpy required. Install with:")
    print("  pip install matplotlib numpy")
    sys.exit(1)

# File extensions to count as code
CODE_EXTENSIONS = {
    '.py', '.js', '.ts', '.jsx', '.tsx', '.java', '.c', '.cpp', '.h', '.hpp',
    '.cs', '.go', '.rs', '.rb', '.php', '.swift', '.kt', '.kts', '.scala',
    '.html', '.css', '.scss', '.sass', '.less', '.vue', '.svelte',
    '.sql', '.sh', '.bash', '.zsh', '.ps1', '.pl', '.lua', '.r',
}

EXCLUDE_DIRS = {
    '__pycache__', '.git', '.svn', '.hg', 'node_modules', 'venv', 
    'env', '.venv', '.env', 'dist', 'build', 'target', '.idea', 
    '.vscode', '.vs', 'bin', 'obj', 'lib', 'libs', 'deps'
}

def get_git_loc_history(repo_path: Path, start_year: int = 2010, end_year: int = 2026, verbose: bool = False):
    """
    Get LOC history from git repository by analyzing commit stats.
    Returns dict of year -> total lines added.
    """
    original_cwd = os.getcwd()
    os.chdir(repo_path)
    
    loc_by_year = defaultdict(int)
    file_count_by_year = defaultdict(int)
    
    # Get list of all code files in the repository
    try:
        # Get all tracked files with specific extensions
        files_cmd = ['git', 'ls-tree', '-r', 'HEAD', '--name-only']
        result = subprocess.run(files_cmd, capture_output=True, text=True, check=True)
        tracked_files = [f for f in result.stdout.split('\n') if f and any(f.endswith(ext) for ext in CODE_EXTENSIONS)]
        
        if verbose:
            print(f"Found {len(tracked_files)} tracked code files")
        
        # For each file, get its commit history
        for file_path in tracked_files:
            if verbose and len(tracked_files) % 100 == 0:
                print(f"Processing file {tracked_files.index(file_path)+1}/{len(tracked_files)}...")
            
            # Get the year when each line was added (using first appearance)
            cmd = ['git', 'log', '--follow', '--format=%ad', '--date=short', '--', file_path]
            try:
                result = subprocess.run(cmd, capture_output=True, text=True, check=True)
                dates = result.stdout.strip().split('\n')
                
                if dates and dates[0]:
                    # Get the first commit date (when file was created)
                    first_date = dates[-1] if len(dates) > 1 else dates[0]
                    year = int(first_date[:4])
                    
                    if start_year <= year <= end_year:
                        # Count lines in the current version of the file
                        with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                            lines = f.readlines()
                            # Count non-empty, non-comment lines (simplified)
                            loc = sum(1 for line in lines if line.strip() and not line.strip().startswith(('#', '//', '/*')))
                            if loc > 0:
                                loc_by_year[year] += loc
                                file_count_by_year[year] += 1
            except subprocess.CalledProcessError:
                continue
                
    except subprocess.CalledProcessError as e:
        print(f"[108051] Error reading git repository: {e}")
        os.chdir(original_cwd)
        return {}
    
    os.chdir(original_cwd)
    
    if verbose:
        print("\n[0] Git history analysis complete:")
        for year in sorted(loc_by_year.keys()):
            print(f"  {year}: {loc_by_year[year]:,} LOC ({file_count_by_year[year]} files)")
    
    return loc_by_year

def scan_archive(archive_path: Path, verbose: bool = False) -> Dict[int, int]:
    """Fallback: Scan archive using file modification dates."""
    loc_by_year = defaultdict(int)
    file_count_by_year = defaultdict(int)
    
    if not archive_path.exists():
        print(f"[108051] Error: Path '{archive_path}' does not exist.")
        return {}
    
    print(f"[0] Scanning filesystem: {archive_path}")
    
    for root, dirs, files in os.walk(archive_path):
        # Filter out excluded directories
        dirs[:] = [d for d in dirs if d not in EXCLUDE_DIRS]
        
        for file in files:
            file_path = Path(root) / file
            ext = file_path.suffix.lower()
            
            if ext not in CODE_EXTENSIONS:
                continue
            
            try:
                mtime = os.path.getmtime(file_path)
                year = datetime.fromtimestamp(mtime).year
                
                if year < 2010 or year > 2026:
                    continue
                
                # Simple line count
                with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                    lines = f.readlines()
                    loc = sum(1 for line in lines if line.strip() and not line.strip().startswith(('#', '//', '/*')))
                
                if loc > 0:
                    loc_by_year[year] += loc
                    file_count_by_year[year] += 1
            except Exception:
                continue
    
    if verbose:
        print("\nFilesystem scan complete:")
        for year in sorted(loc_by_year.keys()):
            print(f"  {year}: {loc_by_year[year]:,} LOC ({file_count_by_year[year]} files)")
    
    return loc_by_year

def generate_graph(loc_by_year: Dict[int, int], output_file: str = "loc_timeline.png"):
    """Generate the timeline graph."""
    if not loc_by_year:
        print("[108051] No data to graph.")
        return
    
    years = sorted(loc_by_year.keys())
    loc_values = [loc_by_year[year] for year in years]
    
    # Create figure
    plt.style.use('seaborn-v0_8-darkgrid')
    fig, ax = plt.subplots(figsize=(14, 8))
    
    # Bar chart
    colors = plt.cm.YlGn(np.linspace(0.4, 0.9, len(years)))
    bars = ax.bar(years, loc_values, color=colors, edgecolor='darkgreen', linewidth=1.5, alpha=0.85)
    
    # Add value labels
    for bar, loc in zip(bars, loc_values):
        height = bar.get_height()
        ax.text(bar.get_x() + bar.get_width()/2., height + max(loc_values)*0.01,
                f'{loc:,}', ha='center', va='bottom', fontsize=9, fontweight='bold')
    
    # Add cumulative line
    cumulative = np.cumsum(loc_values)
    ax2 = ax.twinx()
    ax2.plot(years, cumulative, color='darkred', marker='o', linewidth=2.5, 
             markersize=8, label='Cumulative LOC', zorder=5)
    ax2.set_ylabel('Cumulative Lines of Code', fontsize=11, color='darkred')
    ax2.tick_params(axis='y', labelcolor='darkred')
    
    # Format axes
    ax.set_xticks(range(2010, 2027, 2))
    ax.set_xlim(2009.5, 2026.5)
    ax.set_xlabel('Year', fontsize=12, fontweight='bold')
    ax.set_ylabel('Lines of Code per Year', fontsize=12, fontweight='bold')
    ax.yaxis.set_major_formatter(plt.FuncFormatter(lambda x, p: f'{int(x):,}'))
    
    # Title
    total_loc = sum(loc_values)
    start_year = min(years)
    title = f'📊 Code Evolution Timeline: {start_year} - 2026\nTotal: {total_loc:,} LOC'
    ax.set_title(title, fontsize=16, fontweight='bold', pad=20)
    
    ax.grid(True, alpha=0.3, linestyle='--', linewidth=0.5)
    ax.set_axisbelow(True)
    
    plt.tight_layout()
    plt.savefig(output_file, dpi=150, bbox_inches='tight')
    print(f"✅ [0] Graph saved as: {output_file}")

def main():
    parser = argparse.ArgumentParser(
        description='Analyze lines of code in your archive using git history or file dates'
    )
    parser.add_argument('archive_path', type=str, 
                       help='Path to your archive directory or git repository')
    parser.add_argument('-o', '--output', type=str, default='loc_timeline.png',
                       help='Output filename (default: loc_timeline.png)')
    parser.add_argument('-v', '--verbose', action='store_true',
                       help='Show detailed breakdown')
    parser.add_argument('--no-git', action='store_true',
                       help='Force using filesystem dates instead of git history')
    
    args = parser.parse_args()
    
    archive_path = Path(args.archive_path).expanduser().resolve()
    
    # Try git history first (unless disabled)
    loc_by_year = {}
    if not args.no_git and (archive_path / '.git').exists():
        print("[0] 📊 Using git history for accurate dates...")
        loc_by_year = get_git_loc_history(archive_path, verbose=args.verbose)
    
    # Fallback to filesystem scan
    if not loc_by_year:
        print("[0] 📁 Falling back to file modification dates...")
        loc_by_year = scan_archive(archive_path, verbose=args.verbose)
    
    if loc_by_year:
        generate_graph(loc_by_year, args.output)
        
        # Print summary
        print(f"\n[0] 📈 Summary:")
        print(f"  Total LOC: {sum(loc_by_year.values()):,}")
        print(f"  Peak year: {max(loc_by_year, key=loc_by_year.get)} ({max(loc_by_year.values()):,} LOC)")
        print(f"  Years with code: {len(loc_by_year)}")
    else:
        print("[108051] ❌ No code found. Check your path and file extensions.")

if __name__ == "__main__":
    main()

