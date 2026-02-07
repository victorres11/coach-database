#!/usr/bin/env python3
"""
Fill play caller data using Perplexity Deep Research API.
Queries each team's offensive play caller and updates the coaches DB.
"""

import sqlite3
import json
import time
import sys
import os
import requests
from pathlib import Path

DB_PATH = Path(__file__).parent.parent / 'db' / 'coaches.db'
API_KEY_PATH = os.path.expanduser('~/.openclaw/credentials/perplexity_api_key')

def get_api_key():
    with open(API_KEY_PATH) as f:
        return f.read().strip()

def get_teams_by_conference(conn, conference):
    """Get all teams in a conference with their OCs and HCs."""
    rows = conn.execute('''
        SELECT s.id as school_id, s.name as school, c.id as coach_id, c.name as coach, 
               c.position, c.is_head_coach
        FROM coaches c
        JOIN schools s ON c.school_id = s.id
        JOIN conferences conf ON s.conference_id = conf.id
        WHERE conf.abbrev = ?
        AND (c.position LIKE '%oordinator%' 
             OR c.position LIKE '%play%' 
             OR c.is_head_coach = 1)
        ORDER BY s.name, c.is_head_coach DESC
    ''', (conference,)).fetchall()
    
    # Group by school
    teams = {}
    for r in rows:
        school = r['school']
        if school not in teams:
            teams[school] = {'school_id': r['school_id'], 'coaches': []}
        teams[school]['coaches'].append({
            'coach_id': r['coach_id'],
            'name': r['coach'],
            'position': r['position'],
            'is_head_coach': r['is_head_coach']
        })
    return teams

def query_perplexity(school, coaches_context, api_key):
    """Ask Perplexity who calls plays for a given school."""
    
    coach_list = "\n".join([f"- {c['name']} ({c['position']})" for c in coaches_context])
    
    prompt = f"""Who is the offensive play caller for {school} football in 2025? 

Here is their current coaching staff:
{coach_list}

Please answer specifically:
1. Who calls the offensive plays on game day?
2. Is it the OC, HC, or someone else?
3. If the HC calls plays, note that explicitly.

Be concise. Cite your sources."""

    headers = {
        'Authorization': f'Bearer {api_key}',
        'Content-Type': 'application/json'
    }
    
    payload = {
        'model': 'sonar-pro',
        'messages': [
            {
                'role': 'system',
                'content': 'You are a college football research assistant. Answer concisely with specific names and roles. Always cite sources.'
            },
            {
                'role': 'user', 
                'content': prompt
            }
        ],
        'temperature': 0.1,
        'max_tokens': 500
    }
    
    resp = requests.post(
        'https://api.perplexity.ai/chat/completions',
        headers=headers,
        json=payload,
        timeout=30
    )
    resp.raise_for_status()
    data = resp.json()
    
    answer = data['choices'][0]['message']['content']
    citations = data.get('citations', [])
    
    return answer, citations

def parse_play_caller(school, answer, coaches):
    """Parse Perplexity response to identify the play caller."""
    answer_lower = answer.lower()
    
    # Check if HC calls plays
    hc = next((c for c in coaches if c['is_head_coach']), None)
    hc_calls = False
    if hc:
        hc_last = hc['name'].split()[-1].lower()
        # Check for patterns indicating HC calls plays
        hc_patterns = [
            f"{hc_last} calls",
            f"{hc_last} is the play caller",
            f"head coach calls",
            f"head coach.*calls plays",
            f"{hc_last}.*handles play-calling",
            f"{hc_last}.*play-calling duties",
        ]
        for pattern in hc_patterns:
            if pattern in answer_lower:
                hc_calls = True
                break
    
    # Find which coach is identified as play caller
    best_match = None
    for c in coaches:
        name_parts = c['name'].split()
        last_name = name_parts[-1].lower() if name_parts else ''
        
        if last_name and len(last_name) > 2:
            # Check if this coach is mentioned as play caller
            caller_patterns = [
                f"{last_name} calls",
                f"{last_name} is the play caller",
                f"{last_name}.*play-calling",
                f"{last_name}.*calls the plays",
                f"{last_name}.*handles.*play",
            ]
            for pattern in caller_patterns:
                if pattern in answer_lower:
                    best_match = c
                    break
        if best_match:
            break
    
    # If HC calls plays, return HC
    if hc_calls and hc:
        return hc, True
    
    # If we found a specific coach
    if best_match:
        return best_match, best_match.get('is_head_coach', False)
    
    # Fallback: look for OC
    oc = next((c for c in coaches if 'offensive coordinator' in (c['position'] or '').lower() 
               and 'co-' not in (c['position'] or '').lower()), None)
    if oc:
        return oc, False
    
    return None, False

def main():
    conference = sys.argv[1] if len(sys.argv) > 1 else 'SEC'
    
    api_key = get_api_key()
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    
    # Get teams for any conference
    teams = get_teams_by_conference(conn, conference)
    
    print(f"Processing {len(teams)} {conference} teams...\n")
    
    results = []
    
    for school, data in sorted(teams.items()):
        print(f"🔍 {school}...")
        
        try:
            answer, citations = query_perplexity(school, data['coaches'], api_key)
            play_caller, hc_calls = parse_play_caller(school, answer, data['coaches'])
            
            citation_str = '; '.join(citations[:3]) if citations else 'Perplexity sonar-pro'
            
            result = {
                'school': school,
                'play_caller': play_caller['name'] if play_caller else 'UNKNOWN',
                'position': play_caller['position'] if play_caller else None,
                'hc_calls_plays': hc_calls,
                'source': citation_str,
                'raw_answer': answer
            }
            results.append(result)
            
            # Update DB
            if play_caller:
                conn.execute('''
                    UPDATE coaches SET is_play_caller = 1, play_caller_source = ?
                    WHERE id = ?
                ''', (f"Perplexity: {citation_str}", play_caller['coach_id']))
                
                # Clear any previous play callers for this school
                conn.execute('''
                    UPDATE coaches SET is_play_caller = 0 
                    WHERE school_id = ? AND id != ? AND is_play_caller = 1
                ''', (data['school_id'], play_caller['coach_id']))
                
                conn.commit()
            
            icon = "🏈" if hc_calls else "📋"
            print(f"  {icon} Play caller: {result['play_caller']} ({result['position']})")
            if hc_calls:
                print(f"  ⚠️  HC calls plays!")
            print()
            
            # Rate limit - be nice to the API
            time.sleep(2)
            
        except Exception as e:
            print(f"  ❌ Error: {e}\n")
            results.append({
                'school': school,
                'play_caller': 'ERROR',
                'error': str(e)
            })
    
    # Summary
    print("\n" + "="*60)
    print(f"{'School':25s} | {'Play Caller':25s} | HC?")
    print("-"*60)
    for r in results:
        hc_flag = "✅" if r.get('hc_calls_plays') else ""
        print(f"{r['school']:25s} | {r['play_caller']:25s} | {hc_flag}")
    
    # Save results JSON
    output_path = Path(__file__).parent.parent / 'data' / f'play_callers_{conference.lower()}.json'
    with open(output_path, 'w') as f:
        json.dump(results, f, indent=2)
    print(f"\nResults saved to {output_path}")
    
    conn.close()

if __name__ == '__main__':
    main()
