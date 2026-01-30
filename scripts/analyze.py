#!/usr/bin/env python3
"""
Analyze FBS coach salary data.

Usage:
    python analyze.py [--top N] [--conference CONF] [--by conference]
"""

import argparse
import json
from pathlib import Path
from collections import defaultdict

def load_data(data_path: Path) -> dict:
    """Load coach data from JSON file."""
    with open(data_path) as f:
        return json.load(f)

def format_money(amount: int | None) -> str:
    """Format money amount."""
    if amount is None:
        return "N/A"
    return f"${amount:,}"

def print_coach(coach: dict, rank_width: int = 3):
    """Print a single coach row."""
    rank = str(coach["rank"]).rjust(rank_width)
    name = coach["coach"][:25].ljust(25)
    school = coach["school"][:20].ljust(20)
    salary = format_money(coach.get("totalPay")).rjust(15)
    buyout = format_money(coach.get("buyout")).rjust(15)
    print(f"{rank}. {name} {school} {salary} {buyout}")

def top_coaches(coaches: list, n: int = 25):
    """Show top N highest paid coaches."""
    print(f"\n{'='*80}")
    print(f"TOP {n} HIGHEST PAID FBS HEAD COACHES (2025)")
    print(f"{'='*80}")
    print(f"{'#':>3}  {'Coach':<25} {'School':<20} {'Total Pay':>15} {'Buyout':>15}")
    print("-" * 80)
    
    for coach in coaches[:n]:
        print_coach(coach)

def by_conference(coaches: list):
    """Show breakdown by conference."""
    conf_data = defaultdict(list)
    for coach in coaches:
        conf_data[coach["conference"]].append(coach)
    
    print(f"\n{'='*80}")
    print("SALARY BY CONFERENCE (2025)")
    print(f"{'='*80}")
    
    conf_stats = []
    for conf, conf_coaches in conf_data.items():
        salaries = [c["totalPay"] for c in conf_coaches if c["totalPay"]]
        if salaries:
            avg = sum(salaries) // len(salaries)
            max_sal = max(salaries)
            min_sal = min(salaries)
            conf_stats.append({
                "conference": conf,
                "count": len(conf_coaches),
                "with_data": len(salaries),
                "avg": avg,
                "max": max_sal,
                "min": min_sal,
                "total": sum(salaries)
            })
    
    # Sort by average salary
    conf_stats.sort(key=lambda x: x["avg"], reverse=True)
    
    print(f"{'Conference':<10} {'Teams':>6} {'Avg Salary':>15} {'Max':>15} {'Min':>15}")
    print("-" * 65)
    
    for stat in conf_stats:
        print(f"{stat['conference']:<10} {stat['with_data']:>6} {format_money(stat['avg']):>15} {format_money(stat['max']):>15} {format_money(stat['min']):>15}")

def filter_conference(coaches: list, conf: str):
    """Filter coaches by conference."""
    conf_upper = conf.upper()
    return [c for c in coaches if c["conference"].upper() == conf_upper]

def biggest_buyouts(coaches: list, n: int = 10):
    """Show coaches with biggest buyouts."""
    with_buyout = [c for c in coaches if c.get("buyout")]
    with_buyout.sort(key=lambda x: x["buyout"], reverse=True)
    
    print(f"\n{'='*80}")
    print(f"TOP {n} BIGGEST BUYOUTS")
    print(f"{'='*80}")
    print(f"{'#':>3}  {'Coach':<25} {'School':<20} {'Buyout':>15} {'Salary':>15}")
    print("-" * 80)
    
    for i, coach in enumerate(with_buyout[:n], 1):
        rank = str(i).rjust(3)
        name = coach["coach"][:25].ljust(25)
        school = coach["school"][:20].ljust(20)
        buyout = format_money(coach.get("buyout")).rjust(15)
        salary = format_money(coach.get("totalPay")).rjust(15)
        print(f"{rank}. {name} {school} {buyout} {salary}")

def power_four_analysis(coaches: list):
    """Analyze Power Four conferences specifically."""
    power_four = ["SEC", "Big 10", "Big 12", "ACC"]
    p4_coaches = [c for c in coaches if c["conference"] in power_four]
    
    print(f"\n{'='*80}")
    print("POWER FOUR ANALYSIS")
    print(f"{'='*80}")
    
    for conf in power_four:
        conf_coaches = [c for c in p4_coaches if c["conference"] == conf]
        salaries = [c["totalPay"] for c in conf_coaches if c["totalPay"]]
        if salaries:
            print(f"\n{conf}:")
            print(f"  Coaches: {len(conf_coaches)}")
            print(f"  With salary data: {len(salaries)}")
            print(f"  Average: {format_money(sum(salaries) // len(salaries))}")
            print(f"  Total payroll: {format_money(sum(salaries))}")
            
            # Top 3 in conference
            conf_coaches_sorted = sorted(conf_coaches, key=lambda x: x["totalPay"] or 0, reverse=True)
            print(f"  Top 3:")
            for c in conf_coaches_sorted[:3]:
                print(f"    - {c['coach']} ({c['school']}): {format_money(c['totalPay'])}")

def main():
    parser = argparse.ArgumentParser(description="Analyze FBS coach salary data")
    parser.add_argument("--top", "-t", type=int, default=25, help="Show top N coaches")
    parser.add_argument("--conference", "-c", help="Filter by conference")
    parser.add_argument("--by", choices=["conference"], help="Group by attribute")
    parser.add_argument("--buyouts", action="store_true", help="Show biggest buyouts")
    parser.add_argument("--power-four", "-p4", action="store_true", help="Power Four analysis")
    parser.add_argument("--data", "-d", default="data/coaches.json", help="Data file path")
    args = parser.parse_args()
    
    # Resolve path relative to script location
    script_dir = Path(__file__).parent.parent
    data_path = script_dir / args.data
    
    data = load_data(data_path)
    coaches = data["coaches"]
    
    print(f"Loaded {len(coaches)} coaches from {data['metadata']['lastUpdated']}")
    
    if args.conference:
        coaches = filter_conference(coaches, args.conference)
        print(f"Filtered to {len(coaches)} coaches in {args.conference}")
    
    if args.by == "conference":
        by_conference(coaches)
    elif args.buyouts:
        biggest_buyouts(coaches, args.top)
    elif args.power_four:
        power_four_analysis(coaches)
    else:
        top_coaches(coaches, args.top)

if __name__ == "__main__":
    main()
