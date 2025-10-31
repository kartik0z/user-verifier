# app.py
import streamlit as st
import requests
import json
import datetime
import re
from typing import Dict, Any, List, Optional, Tuple, Set

# --------- Load config ----------
CONFIG_FILE = "config.json"

@st.cache_data
def load_config(path: str = CONFIG_FILE) -> Dict[str, Any]:
    try:
        with open(path, 'r') as f:
            return json.load(f)
    except FileNotFoundError:
        raise FileNotFoundError(f"{path} not found. Create it next to this app.")
    except json.JSONDecodeError:
        raise ValueError(f"{path} is not valid JSON.")

try:
    config = load_config()
except Exception as e:
    st.stop()  # stop rendering below; show error
    raise

FRIENDLY_OWNER_IDS: Set[int] = set(config.get("FRIENDLY_OWNER_IDS", []))
BA_UK_GROUP_IDS: Set[int] = set(config.get("BA_UK_GROUP_IDS", []))
BLACKLISTED_GROUP_IDS: Set[int] = set(config.get("BLACKLISTED_GROUP_IDS", []))
BA_BADGE_IDS: Set[int] = set(config.get("BA_BADGE_IDS", []))
IFD_BLACKLIST_IDS: Set[int] = set(config.get("IFD_BLACKLIST_IDS", []))
BA_BLACKLIST_IDS: Set[int] = set(config.get("BA_BLACKLIST_IDS", []))
NSFW_WORDS: Set[str] = set(config.get("NSFW_WORDS", []))
BA_MEMBER_IMPERSONATION_LIST: Set[str] = set([x.lower() for x in config.get("BA_MEMBER_IMPERSONATION_LIST", [])])

st.set_page_config(page_title="Roblox User Verifier", layout="wide")

# --------- API helper functions (cached where appropriate) ----------
@st.cache_data
def get_user_id_from_username(username: str) -> Optional[int]:
    url = "https://users.roblox.com/v1/usernames/users"
    payload = {"usernames": [username], "excludeBannedUsers": False}
    try:
        r = requests.post(url, json=payload, timeout=12)
        r.raise_for_status()
        data = r.json().get('data', [])
        return data[0]['id'] if data else None
    except requests.RequestException:
        return None

@st.cache_data
def get_user_info(user_id: int) -> Optional[Dict[str, Any]]:
    url = f"https://users.roblox.com/v1/users/{user_id}"
    try:
        r = requests.get(url, timeout=12)
        r.raise_for_status()
        return r.json()
    except requests.RequestException:
        return None

@st.cache_data
def get_user_avatar_url(user_id: int) -> Optional[str]:
    url = f"https://thumbnails.roblox.com/v1/users/avatar-headshot?userIds={user_id}&size=150x150&format=Png&isCircular=false"
    try:
        r = requests.get(url, timeout=12)
        r.raise_for_status()
        data = r.json().get('data', [])
        return data[0]['imageUrl'] if data else None
    except requests.RequestException:
        return None

@st.cache_data
def get_friend_count(user_id: int) -> Optional[int]:
    url = f"https://friends.roblox.com/v1/users/{user_id}/friends/count"
    try:
        r = requests.get(url, timeout=12)
        r.raise_for_status()
        return r.json().get('count')
    except requests.RequestException:
        return None

@st.cache_data
def get_user_groups(user_id: int) -> Optional[List[Dict[str, Any]]]:
    url = f"https://groups.roblox.com/v1/users/{user_id}/groups/roles"
    try:
        r = requests.get(url, timeout=12)
        r.raise_for_status()
        return r.json().get('data', [])
    except requests.RequestException:
        return None

@st.cache_data
def get_oldest_badges(user_id: int, total_limit: int = 90) -> List[Dict[str, Any]]:
    badges = []
    cursor = ""
    page_limit = 100
    base_url = f"https://badges.roblox.com/v1/users/{user_id}/badges"
    while len(badges) < total_limit:
        params = {'limit': page_limit, 'sortOrder': 'Asc'}
        if cursor:
            params['cursor'] = cursor
        try:
            r = requests.get(base_url, params=params, timeout=12)
            r.raise_for_status()
            data = r.json()
            new_badges = data.get('data', [])
            if not new_badges:
                break
            badges.extend(new_badges)
            cursor = data.get('nextPageCursor') or ""
            if not cursor:
                break
        except requests.RequestException:
            break
    return badges[:total_limit]

@st.cache_data
def get_total_badge_count(user_id: int, pass_threshold: int = 300) -> int:
    total_badges = 0
    cursor = ""
    page_limit = 100
    base_url = f"https://badges.roblox.com/v1/users/{user_id}/badges"
    while True:
        params = {'limit': page_limit, 'sortOrder': 'Desc'}
        if cursor:
            params['cursor'] = cursor
        try:
            r = requests.get(base_url, params=params, timeout=12)
            r.raise_for_status()
            data = r.json()
            new_badges = data.get('data', [])
            if not new_badges:
                break
            total_badges += len(new_badges)
            if total_badges >= pass_threshold:
                return total_badges
            cursor = data.get('nextPageCursor') or ""
            if not cursor:
                break
        except requests.RequestException:
            break
    return total_badges

# --------- Logic functions ----------
MIN_ACCOUNT_AGE_DAYS = 60
MIN_FRIEND_COUNT = 30
MIN_NON_BA_GROUP_COUNT = 13
MIN_BADGE_COUNT = 300
OLDEST_BADGES_TO_CHECK = 90
USERNAME_DIGIT_THRESHOLD = 4

def check_account_age(user_info: Dict[str, Any]) -> Tuple[bool, str]:
    created_str = user_info.get('created')
    if not created_str:
        return True, "Could not verify account age."
    if 'Z' in created_str:
        created_date = datetime.datetime.fromisoformat(created_str.replace('Z', '+00:00'))
    else:
        try:
            created_date = datetime.datetime.fromisoformat(created_str)
            if created_date.tzinfo is None:
                created_date = created_date.replace(tzinfo=datetime.timezone.utc)
        except ValueError:
            return True, f"Could not parse account creation date: {created_str}"
    age = datetime.datetime.now(datetime.timezone.utc) - created_date
    days_old = age.days
    if days_old < MIN_ACCOUNT_AGE_DAYS:
        return True, f"Account is {days_old} days old (under {MIN_ACCOUNT_AGE_DAYS})."
    return False, f"Account is {days_old} days old."

def check_username(user_info: Dict[str, Any]) -> Tuple[Optional[str], Optional[str]]:
    username = user_info.get('name', '').lower()
    if "alt" in username:
        return "Username contains 'alt'.", None
    if username in BA_MEMBER_IMPERSONATION_LIST:
        return "Username impersonates a BA member.", None
    for word in NSFW_WORDS:
        if word in username:
            return f"Username contains offensive word: '{word}'.", None
    return None, None

def check_social_activity(user_id: int, groups: List[Dict[str, Any]]) -> List[str]:
    red_flags = []
    friend_count = get_friend_count(user_id)
    if friend_count is None:
        red_flags.append("Could not verify friend count.")
    elif friend_count < MIN_FRIEND_COUNT:
        red_flags.append(f"Fewer than {MIN_FRIEND_COUNT} friends ({friend_count}).")
    non_ba_groups = [g for g in groups if g['group']['id'] not in BA_UK_GROUP_IDS]
    non_ba_group_count = len(non_ba_groups)
    if non_ba_group_count < MIN_NON_BA_GROUP_COUNT:
        red_flags.append(f"Fewer than {MIN_NON_BA_GROUP_COUNT} non-BA groups ({non_ba_group_count}).")
    badge_count = get_total_badge_count(user_id, MIN_BADGE_COUNT)
    if badge_count < MIN_BADGE_COUNT:
        red_flags.append(f"Fewer than 10 pages of badges ({badge_count} total).")
    oldest_badges = get_oldest_badges(user_id, OLDEST_BADGES_TO_CHECK)
    for badge in oldest_badges:
        if badge.get('id') in BA_BADGE_IDS:
            red_flags.append(f"BA-related badge found in oldest 3 pages (ID: {badge.get('id')}).")
            break
    return red_flags

def check_blacklists(user_id: int, groups: List[Dict[str, Any]], ifd_blacklist: Set[int]) -> List[str]:
    dismissals = []
    if user_id in ifd_blacklist:
        dismissals.append("User is on the IFD Blacklist.")
    if user_id in BA_BLACKLIST_IDS:
        dismissals.append("User is on the BA Blacklist.")
    for item in groups:
        group = item.get('group', {})
        group_id = group.get('id')
        group_name = group.get('name', '').lower()
        owner = group.get('owner')
        owner_id = owner.get('userId') if isinstance(owner, dict) else None
        if group_id in BLACKLISTED_GROUP_IDS:
            dismissals.append(f"User is in a blacklisted group: {group.get('name')}.")
        if ("british army" in group_name) and (group_id not in BA_UK_GROUP_IDS) and (owner_id not in FRIENDLY_OWNER_IDS):
            dismissals.append(f"User is in another British Army group: {group.get('name')}.")
    return dismissals

@st.cache_data
def fetch_live_blacklist(sheet_csv_url: str) -> Set[int]:
    from urllib.parse import urlparse

    # Add URL validation to prevent SSRF
    try:
        parsed_url = urlparse(sheet_csv_url)
        if parsed_url.hostname != 'docs.google.com':
            st.warning("Warning: Live blacklist URL must be from 'docs.google.com'.")
            return set()
    except Exception as e:
        st.warning(f"Warning: Invalid URL provided for live blacklist. {e}")
        return set()

    try:
        r = requests.get(sheet_csv_url, timeout=12)
        r.raise_for_status()
        lines = r.text.strip().splitlines()
        ids = set()
        for line in lines:
            cols = [x.strip() for x in line.split(',')]
            for col in cols:
                if col.isdigit():
                    ids.add(int(col))
        return ids
    except requests.RequestException:
        return set()

# --------- UI ----------
st.title("Roblox User Verifier")

st.sidebar.title("Verification Options")
username = st.sidebar.text_input("Roblox username", value="", help="Enter the Roblox username to verify.")
sheet_url = st.sidebar.text_input("Optional: Live blacklist CSV URL (public Google Sheet export URL)", value="", help="Provide CSV export link to include more blacklist IDs.")
run = st.sidebar.button("Run Verification")

st.sidebar.markdown("---")

with st.sidebar.expander("Config summary"):
    st.write(
        {
            "Friendly owner IDs": len(FRIENDLY_OWNER_IDS),
            "BA UK groups": len(BA_UK_GROUP_IDS),
            "Blacklisted groups": len(BLACKLISTED_GROUP_IDS),
            "BA badge IDs": len(BA_BADGE_IDS),
            "IFD blacklist users": len(IFD_BLACKLIST_IDS),
            "BA blacklist users": len(BA_BLACKLIST_IDS),
            "NSFW words": len(NSFW_WORDS),
        }
    )

st.markdown("--- ")

if run:
    if not username:
        st.error("Provide a username.")
    else:
        with st.spinner("Fetching user id..."):
            user_id = get_user_id_from_username(username)
        if not user_id:
            st.error(f"User '{username}' not found.")
        else:
            st.success(f"Found user id: {user_id}")
            with st.spinner("Fetching user info..."):
                user_info = get_user_info(user_id)
                groups = get_user_groups(user_id)
            if user_info is None:
                st.error("Could not fetch user info from Roblox API.")
            elif groups is None:
                st.error("Could not fetch groups from Roblox API.")
            else:
                # Optionally merge live blacklist
                if sheet_url:
                    with st.spinner("Fetching live blacklist..."):
                        new_ids = fetch_live_blacklist(sheet_url)
                    if new_ids:
                        st.info(f"Loaded {len(new_ids)} IDs from live blacklist. Merging into IFD blacklist for this run.")
                        # Merge into a copy (do not mutate global config)
                        temp_ifd = set(IFD_BLACKLIST_IDS) | set(new_ids)
                    else:
                        st.warning("Could not load blacklist or no IDs found at provided URL.")
                        temp_ifd = set(IFD_BLACKLIST_IDS)
                else:
                    temp_ifd = set(IFD_BLACKLIST_IDS)

                # Run checks
                instant_dismissals: List[str] = []
                red_flags: List[str] = []

                is_dismissed, age_reason = check_account_age(user_info)
                if is_dismissed:
                    instant_dismissals.append(age_reason)

                dismissal_reason, flag_reason = check_username(user_info)
                if dismissal_reason:
                    instant_dismissals.append(dismissal_reason)
                if flag_reason:
                    red_flags.append(flag_reason)

                instant_dismissals.extend(check_blacklists(user_id, groups, temp_ifd))

                # Early dismissal UI
                st.header("Summary")

                col1, col2 = st.columns([1, 4])
                with col1:
                    avatar_url = get_user_avatar_url(user_id)
                    if avatar_url:
                        st.image(avatar_url, caption=user_info.get('name'), width=150)
                    else:
                        st.write("No avatar found.")

                with col2:
                    st.write(f"**Display Name:** {user_info.get('displayName')}")
                    st.write(f"**Username:** @{user_info.get('name')}")
                    st.write(f"**User ID:** {user_id}")
                    st.markdown(f"**[View Profile on Roblox](https://www.roblox.com/users/{user_id}/profile)**")

                if instant_dismissals:
                    st.error("### ❌ INSTANT DISMISSAL")
                    for i, r in enumerate(instant_dismissals, 1):
                        st.error(f"{i}. {r}")
                    st.stop()

                with st.spinner("Running social activity checks (friends, groups, badges)..."):
                    activity_flags = check_social_activity(user_id, groups)
                red_flags.extend(activity_flags)

                st.subheader("Final Report")
                st.metric("Total Red Flags", len(red_flags))

                if len(red_flags) >= 2:
                    st.error("### ❌ DISMISSED (2+ red flags)")
                else:
                    st.success("### ✅ VERIFIED (fewer than 2 red flags)")

                if red_flags:
                    st.write("#### Red Flags Found:")
                    for i, r in enumerate(red_flags, 1):
                        st.warning(f"{i}. {r}")
                else:
                    st.write("No red flags found.")

                st.info(
                    """
                    ### Manual checks required
                    - Review friends list for suspicious / 'bacon' alts.
                    - Manually inspect groups listed below.
                    """
                )

                # Show groups table
                with st.expander("Groups (first 200 shown)"):
                    if groups:
                        groups_display = [
                            {
                                "group_id": g['group'].get('id'),
                                "group_name": g['group'].get('name'),
                                "role": g.get('role', {}).get('name')
                                if isinstance(g.get('role'), dict)
                                else g.get('role'),
                                "owner_id": g['group'].get('owner', {}).get('userId')
                                if isinstance(g['group'].get('owner'), dict)
                                else None,
                            }
                            for g in groups[:200]
                        ]
                        st.table(groups_display)
                    else:
                        st.write("No groups found or could not fetch groups.")

                # Show oldest badges summary
                with st.expander("Oldest badges (sample)"):
                    with st.spinner("Fetching oldest badges..."):
                        oldest = get_oldest_badges(user_id, 30)
                    if oldest:
                        badges_display = [
                            {
                                "id": b.get('id'),
                                "name": b.get('name'),
                                "awarded": b.get('awarded') or b.get('awardedAt'),
                            }
                            for b in oldest
                        ]
                        st.table(badges_display)
                    else:
                        st.write("No badges or could not fetch badges.")

                # Allow download of the report JSON
                report = {
                    "user_id": user_id,
                    "displayName": user_info.get('displayName'),
                    "username": user_info.get('name'),
                    "instant_dismissals": instant_dismissals,
                    "red_flags": red_flags,
                    "groups_count": len(groups),
                    "friend_count": get_friend_count(user_id),
                }
                st.download_button("Download report (JSON)", json.dumps(report, indent=2), file_name=f"report_{user_id}.json", mime="application/json")
