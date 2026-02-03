#!/usr/bin/env python3
"""
Fix duplicate schools and malformed coach names in the database.

Issues fixed:
1. Merge duplicate schools (Texas A&M, Ole Miss, Pitt) 
2. Clean malformed names (e.g., "Dottin-CarterDennis Dottin-Carter" -> "Dennis Dottin-Carter")
3. Remove duplicate coach entries

Usage:
    python scripts/fix_duplicates.py          # Dry run
    python scripts/fix_duplicates.py --apply  # Apply changes
"""

import argparse
import re
import sqlite3
from pathlib import Path

DB_PATH = Path(__file__).parent.parent / "db" / "coaches.db"

# Schools to merge: (keep_id, delete_id, description)
SCHOOL_MERGES = [
    (32, 252, "Texas A&M: merge texas-am (252) into texas-a&m (32)"),
    (10, 266, "Ole Miss: merge ole-miss (266) into mississippi (10)"),
    (28, 231, "Pitt: merge pitt (231) into pittsburgh (28)"),
]


def fix_malformed_name(name: str) -> str:
    """Fix names like 'Dottin-CarterDennis Dottin-Carter' -> 'Dennis Dottin-Carter'
    
    The issue: A hidden <span> with a sort key (last name portion) wasn't properly removed,
    resulting in: <sort-key><visible-name> with no space between them.
    
    We only fix clear cases where:
    1. The first "word" contains concatenated text (sort-key + first-name)
    2. The last name appears again at the end
    3. The reconstructed name makes sense
    """
    if not name or ' ' not in name:
        return name
    
    parts = name.split()
    if len(parts) < 2:
        return name
    
    first_part = parts[0]
    rest = ' '.join(parts[1:])
    rest_parts = rest.split()
    
    if not rest_parts:
        return name
    
    last_name = rest_parts[-1]  # The actual last name (might be hyphenated)
    
    # Only try to fix if first_part is suspiciously long (likely concatenated)
    # Normal first names are rarely > 10 chars, concatenated ones often are
    if len(first_part) < 8:
        return name
    
    # Look for the pattern: the last name (or significant part of it) appears 
    # at the START of first_part, followed by a capitalized first name
    
    # For hyphenated names like "Dottin-Carter", the sort key might be "Dottin-Carter" or just part
    # For "Mc" names like "McDaniel", the sort key is often "Daniel" (without Mc)
    
    last_name_normalized = last_name.lower().replace('-', '').replace("'", "")
    
    # Try to find where a first name starts (look for capital letter after some prefix)
    best_match = None
    for i in range(3, len(first_part) - 1):  # Need at least 3 chars for prefix, 2 for first name
        prefix = first_part[:i].lower().replace('-', '').replace("'", "")
        suffix = first_part[i:]
        
        # The suffix must start with an uppercase letter (start of first name)
        if not suffix or not suffix[0].isupper():
            continue
            
        # The prefix should be a significant portion of the last name
        # For "Dottin-CarterDennis" -> prefix could be "dottin-carter" or "dottincarter"
        # For "DanielArchie" (from McDaniel) -> prefix is "daniel"
        
        # Check if prefix is contained in last_name or vice versa (handles Mc/Mac cases)
        if (prefix in last_name_normalized or 
            last_name_normalized in prefix or
            last_name_normalized.endswith(prefix) or
            prefix.endswith(last_name_normalized)):
            # Found a likely match
            if best_match is None or len(prefix) > len(best_match[0]):
                best_match = (prefix, suffix)
    
    if best_match:
        suffix = best_match[1]
        # Don't apply fix if resulting first name looks incomplete (single letter/initial)
        # e.g., "J. Brown" from "BrownJ.B. Brown" is wrong
        if re.match(r'^[A-Z]\.\s', suffix) or len(suffix) <= 2:
            return name
        return f"{suffix} {rest}"
    
    return name


def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def merge_schools(conn, keep_id: int, delete_id: int, dry_run: bool = True):
    """Merge coaches from delete_id school into keep_id school."""
    cursor = conn.cursor()
    
    # Get school names for logging
    cursor.execute("SELECT name FROM schools WHERE id = ?", (keep_id,))
    keep_name = cursor.fetchone()
    cursor.execute("SELECT name FROM schools WHERE id = ?", (delete_id,))
    delete_name = cursor.fetchone()
    
    if not keep_name or not delete_name:
        print(f"  ⚠️  School not found: keep={keep_id}, delete={delete_id}")
        return 0
    
    # Count coaches to merge
    cursor.execute("SELECT COUNT(*) FROM coaches WHERE school_id = ?", (delete_id,))
    count = cursor.fetchone()[0]
    print(f"  Merging {count} coaches from '{delete_name[0]}' (ID {delete_id}) into '{keep_name[0]}' (ID {keep_id})")
    
    if dry_run:
        return count
    
    # Update coaches to point to the kept school
    cursor.execute(
        "UPDATE coaches SET school_id = ? WHERE school_id = ?",
        (keep_id, delete_id)
    )
    
    # Delete the duplicate school
    cursor.execute("DELETE FROM schools WHERE id = ?", (delete_id,))
    
    return count


def clean_coach_names(conn, dry_run: bool = True):
    """Fix malformed coach names."""
    cursor = conn.cursor()
    
    # Find potentially malformed names (contain pattern like "LastFirstName Last")
    cursor.execute("SELECT id, name FROM coaches")
    rows = cursor.fetchall()
    
    fixed = 0
    for row in rows:
        original = row['name']
        cleaned = fix_malformed_name(original)
        
        if cleaned != original:
            print(f"  Fix name: '{original}' -> '{cleaned}'")
            fixed += 1
            
            if not dry_run:
                cursor.execute(
                    "UPDATE coaches SET name = ? WHERE id = ?",
                    (cleaned, row['id'])
                )
    
    return fixed


def remove_duplicate_coaches(conn, dry_run: bool = True):
    """Remove duplicate coach entries (same name + school + position)."""
    cursor = conn.cursor()
    
    # Find duplicates
    cursor.execute('''
        SELECT name, school_id, position, COUNT(*) as cnt, GROUP_CONCAT(id) as ids
        FROM coaches
        GROUP BY name, school_id, position
        HAVING cnt > 1
    ''')
    
    duplicates = cursor.fetchall()
    removed = 0
    
    for row in duplicates:
        ids = [int(x) for x in row['ids'].split(',')]
        keep_id = ids[0]  # Keep the first one
        delete_ids = ids[1:]
        
        print(f"  Duplicate: '{row['name']}' at school {row['school_id']} - keeping ID {keep_id}, removing {delete_ids}")
        removed += len(delete_ids)
        
        if not dry_run:
            for did in delete_ids:
                cursor.execute("DELETE FROM coaches WHERE id = ?", (did,))
    
    return removed


def main():
    parser = argparse.ArgumentParser(description="Fix duplicate schools and malformed names")
    parser.add_argument("--apply", action="store_true", help="Apply changes (default is dry run)")
    args = parser.parse_args()
    
    dry_run = not args.apply
    
    if dry_run:
        print("🔍 DRY RUN - No changes will be made\n")
    else:
        print("⚠️  APPLYING CHANGES\n")
    
    conn = get_db()
    
    # 1. Merge duplicate schools
    print("1. Merging duplicate schools...")
    merged = 0
    for keep_id, delete_id, desc in SCHOOL_MERGES:
        print(f"\n  {desc}")
        merged += merge_schools(conn, keep_id, delete_id, dry_run)
    print(f"\n  Total coaches merged: {merged}")
    
    # 2. Clean malformed names
    print("\n2. Cleaning malformed coach names...")
    fixed = clean_coach_names(conn, dry_run)
    print(f"  Total names fixed: {fixed}")
    
    # 3. Remove duplicate coaches
    print("\n3. Removing duplicate coach entries...")
    removed = remove_duplicate_coaches(conn, dry_run)
    print(f"  Total duplicates removed: {removed}")
    
    if not dry_run:
        conn.commit()
        print("\n✅ Changes committed to database")
    else:
        print("\n💡 Run with --apply to make changes")
    
    conn.close()


if __name__ == "__main__":
    main()
