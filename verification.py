import requests
import json
import datetime
import re
from typing import Dict, Any, List, Optional, Tuple

# --- Configuration ---

CONFIG_FILE = "config.json"

try:
    with open(CONFIG_FILE, 'r') as f:
        config = json.load(f)
except FileNotFoundError:
    print(f"Error: {CONFIG_FILE} not found. Please create it.")
    exit()
except json.JSONDecodeError:
    print(f"Error: {CONFIG_FILE} is not valid JSON.")
    exit()

# Load configuration values
FRIENDLY_OWNER_IDS = set(config.get("FRIENDLY_OWNER_IDS", []))
BA_UK_GROUP_IDS = set(config.get("BA_UK_GROUP_IDS", []))
BLACKLISTED_GROUP_IDS = set(config.get("BLACKLISTED_GROUP_IDS", []))
BA_BADGE_IDS = set(config.get("BA_BADGE_IDS", []))
IFD_BLACKLIST_IDS = set(config.get("IFD_BLACKLIST_IDS", []))
BA_BLACKLIST_IDS = set(config.get("BA_BLACKLIST_IDS", []))
NSFW_WORDS = set(config.get("NSFW_WORDS", []))
BA_MEMBER_IMPERSONATION_LIST = set(config.get("BA_MEMBER_IMPERSONATION_LIST", []))

# --- API Functions ---

def get_user_id_from_username(username: str) -> Optional[int]:
    """Gets a user's ID from their username."""
    url = "https://users.roblox.com/v1/usernames/users"
    payload = {"usernames": [username], "excludeBannedUsers": False}
    try:
        response = requests.post(url, json=payload)
        response.raise_for_status()
        data = response.json().get('data')
        if data and len(data) > 0:
            return data[0]['id']
        else:
            return None
    except requests.RequestException as e:
        print(f"  [API Error] Could not fetch user ID: {e}")
        return None

def get_user_info(user_id: int) -> Optional[Dict[str, Any]]:
    """Gets a user's public info (creation date, username)."""
    url = f"https://users.roblox.com/v1/users/{user_id}"
    try:
        response = requests.get(url)
        response.raise_for_status()
        return response.json()
    except requests.RequestException as e:
        print(f"  [API Error] Could not fetch user info: {e}")
        return None

def get_friend_count(user_id: int) -> Optional[int]:
    """Gets a user's friend count."""
    url = f"https://friends.roblox.com/v1/users/{user_id}/friends/count"
    try:
        response = requests.get(url)
        response.raise_for_status()
        return response.json().get('count')
    except requests.RequestException as e:
        print(f"  [API Error] Could not fetch friend count: {e}")
        return None

def get_user_groups(user_id: int) -> Optional[List[Dict[str, Any]]]:
    """Gets all groups a user is in."""
    url = f"https://groups.roblox.com/v1/users/{user_id}/groups/roles"
    try:
        response = requests.get(url)
        response.raise_for_status()
        return response.json().get('data', [])
    except requests.RequestException as e:
        print(f"  [API Error] Could not fetch user groups: {e}")
        return None

def get_oldest_badges(user_id: int, total_limit: int = 90) -> List[Dict[str, Any]]:
    """
    Gets the OLDEST badges, up to the total_limit (default 90).
    Fetches in pages (max 100) in Ascending order.
    """
    badges = []
    cursor = "" # Start with no cursor
    page_limit = 100 # 30 is an invalid limit. Valid are 10, 25, 50, 100.
    
    # Base URL without query parameters
    base_url = f"https://badges.roblox.com/v1/users/{user_id}/badges"
    
    while len(badges) < total_limit:
        # --- FIX APPLIED ---
        # Parameters that are always present
        params = {
            'limit': page_limit,
            'sortOrder': 'Asc' # Changed sortOrder to Asc to get oldest first
        }
        # Only add the 'cursor' key if the cursor is not None or an empty string
        if cursor:
            params['cursor'] = cursor
        # --- END FIX ---
        
        try:
            # Use the base_url and the params dictionary
            response = requests.get(base_url, params=params)
            response.raise_for_status()
            data = response.json()
            
            new_badges = data.get('data', [])
            if not new_badges: # No more badges
                break
                
            badges.extend(new_badges)
            cursor = data.get('nextPageCursor')
            
            if not cursor: # No more pages
                break
        except requests.RequestException as e:
            print(f"  [API Error] Could not fetch oldest badges: {e}")
            break
            
    return badges[:total_limit] # Return only up to the limit

def get_total_badge_count(user_id: int, pass_threshold: int = 300) -> int:
    """
    Counts user's badges efficiently.
    Stops counting and returns as soon as count >= pass_threshold (default 300).
    Uses Descending sort (newest first) as it's typically fastest for counting.
    """
    total_badges = 0
    cursor = "" # Start with no cursor
    page_limit = 100 # 30 is an invalid limit. Valid are 10, 25, 50, 100.

    # Base URL without query parameters
    base_url = f"https://badges.roblox.com/v1/users/{user_id}/badges"

    while True:
        # --- FIX APPLIED ---
        # Parameters that are always present
        params = {
            'limit': page_limit,
            'sortOrder': 'Desc'
        }
        # Only add the 'cursor' key if the cursor is not None or an empty string
        if cursor:
            params['cursor'] = cursor
        # --- END FIX ---
        
        try:
            # Use the base_url and the params dictionary
            response = requests.get(base_url, params=params)
            response.raise_for_status()
            data = response.json()
            
            new_badges = data.get('data', [])
            num_new_badges = len(new_badges)
            
            if num_new_badges == 0: # No more badges
                break
                
            total_badges += num_new_badges
            
            if total_badges >= pass_threshold:
                # We have met the threshold, no need to count anymore.
                return total_badges 
                
            cursor = data.get('nextPageCursor')
            if not cursor: # No more pages
                break
                
        except requests.RequestException as e:
            print(f"  [API Error] Could not complete badge count: {e}")
            break # Return the count we have so far
            
    return total_badges

# --- Verification Logic Functions ---

def check_account_age(user_info: Dict[str, Any]) -> Tuple[bool, str]:
    """Checks if account is >= 60 days old."""
    print("  Checking account age...")
    created_str = user_info.get('created')
    if not created_str:
        return True, "Could not verify account age."
    
    # Handle modern ISO format with 'Z'
    if 'Z' in created_str:
        created_date = datetime.datetime.fromisoformat(created_str.replace('Z', '+00:00'))
    # Handle older formats if necessary (though fromisoformat is good)
    else:
        try:
            created_date = datetime.datetime.fromisoformat(created_str)
            if created_date.tzinfo is None:
                created_date = created_date.replace(tzinfo=datetime.timezone.utc)
        except ValueError:
             return True, f"Could not parse account creation date: {created_str}"

    age = datetime.datetime.now(datetime.timezone.utc) - created_date
    days_old = age.days
    
    if days_old < 60:
        return True, f"Account is {days_old} days old (under 60)."
    return False, f"Account is {days_old} days old."

def check_username(user_info: Dict[str, Any]) -> Tuple[Optional[str], Optional[str]]:
    """Checks username rules."""
    print("  Checking username rules...")
    username = user_info.get('name', '').lower()
    
    # Instant Dismissal Checks
    if "alt" in username:
        return "Username contains 'alt'.", None
    if username in BA_MEMBER_IMPERSONATION_LIST:
        return "Username impersonates a BA member.", None
    for word in NSFW_WORDS:
        if word in username:
            return f"Username contains offensive word: '{word}'.", None
    return None, None

def check_social_activity(user_id: int, groups: List[Dict[str, Any]]) -> List[str]:
    """Checks friends, groups, and badges for red flags."""
    red_flags = []
    
    # 1. Friend Count
    print("  Checking friend count...")
    friend_count = get_friend_count(user_id)
    if friend_count is None:
        red_flags.append("Could not verify friend count.")
    elif friend_count < 30:
        red_flags.append(f"Fewer than 30 friends ({friend_count}).")
    # Note: Checking for "bacon" alts must be done manually.

    # 2. Group Count
    print("  Checking group count...")
    non_ba_groups = [g for g in groups if g['group']['id'] not in BA_UK_GROUP_IDS]
    non_ba_group_count = len(non_ba_groups)
    if non_ba_group_count < 13:
        red_flags.append(f"Fewer than 13 non-BA groups ({non_ba_group_count}).")
    
    # 3. Badge Count & Early BA Badges
    print("  Checking badge count (efficiently)...")
    # Check for at least 300 badges
    badge_count = get_total_badge_count(user_id, 300)
    
    if badge_count < 300:
        red_flags.append(f"Fewer than 10 pages of badges ({badge_count} total).")
    
    print("  Checking oldest 3 pages (90 badges)...")
    # Check oldest 90 badges
    oldest_badges = get_oldest_badges(user_id, 90)
    for badge in oldest_badges:
        if badge['id'] in BA_BADGE_IDS:
            red_flags.append(f"BA-related badge found in oldest 3 pages (ID: {badge['id']}).")
            break
            
    return red_flags

def check_blacklists(user_id: int, groups: List[Dict[str, Any]]) -> List[str]:
    """Checks all blacklists and group restrictions."""
    dismissals = []
    
    # 1. User Blacklists
    print("  Checking blacklists...")
    if user_id in IFD_BLACKLIST_IDS:
        dismissals.append("User is on the IFD Blacklist.")
    if user_id in BA_BLACKLIST_IDS:
        dismissals.append("User is on the BA Blacklist.")
        
    # 2. Group Blacklists & Restrictions
    print("  Checking group restrictions...")
    for item in groups:
        group = item.get('group', {})
        group_id = group.get('id')
        group_name = group.get('name', '').lower()

        owner = group.get('owner')
        owner_id = owner.get('userId') if isinstance(owner, dict) else None

        if group_id in BLACKLISTED_GROUP_IDS:
            dismissals.append(f"User is in a blacklisted group: {group.get('name')}.")

        if ("british army" in group_name) and \
            (group_id not in BA_UK_GROUP_IDS) and \
            (owner_id not in FRIENDLY_OWNER_IDS):
            dismissals.append(f"User is in another British Army group: {group.get('name')}.")

            
    return dismissals

def fetch_live_blacklist(sheet_csv_url: str) -> set[int]:
    """
    Reads the 'Blacklist' sheet (CSV export link) and returns a set of user IDs.
    Expects a column containing Roblox User IDs.
    """
    try:
        response = requests.get(sheet_csv_url)
        response.raise_for_status()
        lines = response.text.strip().splitlines()
        blacklist_ids = set()
        for line in lines:
            # Split by comma and clean whitespace
            cols = [x.strip() for x in line.split(',')]
            for col in cols:
                if col.isdigit():  # Roblox IDs are numeric
                    blacklist_ids.add(int(col))
        print(f"Loaded {len(blacklist_ids)} IDs from Google Sheet blacklist.")
        return blacklist_ids
    except requests.RequestException as e:
        print(f"[Error] Could not fetch Google Sheet: {e}")
        return set()

# --- Main Execution ---

def main():
    print("Roblox User Verification Script")
    print("=" * 30)
    
    username = input("Enter the Roblox username to verify: ").strip()
    if not username:
        print("No username provided.")
        return

    # --- 1. Get User Info ---
    print(f"\nFetching data for '{username}'...")
    user_id = get_user_id_from_username(username)
    if not user_id:
        print(f"Error: User '{username}' not found.")
        return
        
    user_info = get_user_info(user_id)
    if not user_info:
        print("Error: Could not fetch user info.")
        return
        
    print(f"  > Found User: {user_info.get('displayName')} (@{user_info.get('name')})")
    print(f"  > User ID: {user_id}")

    # --- 2. Initialize Report ---
    instant_dismissals = []
    red_flags = []

    # --- 3. Run Instant Dismissal Checks ---
    print("\nRunning Instant Dismissal Checks...")
    
    # Age
    is_dismissed, reason = check_account_age(user_info)
    if is_dismissed:
        instant_dismissals.append(reason)
    
    # Username
    dismissal_reason, flag_reason = check_username(user_info)
    if dismissal_reason:
        instant_dismissals.append(dismissal_reason)
    if flag_reason:
        red_flags.append(flag_reason) # Add username red flag
        
    # Blacklists & Groups
    groups = get_user_groups(user_id)
    if groups is None:
        print("Error: Could not fetch user groups. Aborting.")
        return
        
    blacklist_reasons = check_blacklists(user_id, groups)
    instant_dismissals.extend(blacklist_reasons)

    # --- 4. Check for Early Dismissal ---
    if instant_dismissals:
        print("\n" + "=" * 30)
        print("  FINAL REPORT")
        print("=" * 30)
        print(f"  User: {user_info.get('displayName')} (@{user_info.get('name')})")
        print("  Status: ❌ INSTANT DISMISSAL")
        print("\n  Reasons:")
        for i, reason in enumerate(instant_dismissals, 1):
            print(f"    {i}. {reason}")
        print("=" * 30)
        return

    # --- 5. Run Red Flag Checks ---
    print("\nRunning Red Flag Checks...")
    activity_flags = check_social_activity(user_id, groups)
    red_flags.extend(activity_flags)

    # --- 6. Final Evaluation ---
    print("\n" + "=" * 30)
    print("  FINAL REPORT")
    print("=" * 30)
    print(f"  User: {user_info.get('displayName')} (@{user_info.get('name')})")
    
    # Updated rule: Dismiss only if MORE than 2 red flags (e.g., 3+)
    if len(red_flags) >= 2:
        print(f"  Status: ❌ DISMISSED (More than 2 red flags)")
    else:
        print(f"  Status: ✅ VERIFIED")
        
    print(f"\n  Total Red Flags: {len(red_flags)}")
    if red_flags:
        for i, reason in enumerate(red_flags, 1):
            print(f"    {i}. {reason}")
    else:
        print("    No red flags found.")
        
    print("\n  Manual Checks Required:")
    print("    - Review friends list for suspicious/'bacon' alts.")
    print("=" * 30)


if __name__ == "__main__":
    main()