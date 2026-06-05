import streamlit as st
import pandas as pd
import requests
import time
from time import sleep

st.set_page_config(
    page_title="Discogs Collection Comparator",
    page_icon="🎵",
    layout="wide"
)

st.title("🎵 Discogs Collection Comparator")
st.caption("Compare multiple Discogs collections, discover overlap, and export results.")

token = st.text_input("Discogs Personal Access Token", type="default")

usernames_text = st.text_area(
    "Discogs usernames (one per line)",
    placeholder="Sikamixoticelixer\nChibi\nTimo\nUrsa",
    height=120
)


# -----------------------------
# Wat error codes van Discogs zelf...
# -----------------------------
def request_with_retry(url, headers, max_retries=5):
    for attempt in range(max_retries):
        response = requests.get(url, headers=headers)

        if response.status_code == 200:
            return response

        # Rate limit
        if response.status_code == 429:
            retry_after = int(response.headers.get("Retry-After", 2))
            time.sleep(retry_after)
            continue

        # Temporary server issues
        if response.status_code in [500, 502, 503, 504]:
            time.sleep(2 ** attempt)
            continue

        raise Exception(f"Request failed: {response.status_code} - {response.text}")

    raise Exception(f"Max retries exceeded for URL: {url}")


# -----------------------------
# Get all collection folders
# -----------------------------
def get_folders(username, headers):
    url = f"https://api.discogs.com/users/{username}/collection/folders"
    response = request_with_retry(url, headers)
    data = response.json()

    return [folder["id"] for folder in data.get("folders", [])]


# -----------------------------
# Fetch full collection (ALL folders)
# -----------------------------
def get_collection(username, headers):

    releases = []
    folder_ids = get_folders(username, headers)

    for folder_id in folder_ids:

        page = 1
        per_page = 100

        while True:

            url = (
                f"https://api.discogs.com/users/{username}/collection/folders/"
                f"{folder_id}/releases?page={page}&per_page={per_page}"
            )

            response = request_with_retry(url, headers)
            data = response.json()

            for item in data.get("releases", []):

                info = item["basic_information"]

                artists = info.get("artists", [])

                artist_names = [
                    artist.get("name", "").replace(" (2)", "")
                    for artist in artists
                ]

                releases.append({
                    "release_id": info["id"],
                    "artist": " / ".join(artist_names),
                    "title": info["title"],
                    "thumb": info.get("thumb", "")
                })

            pagination = data.get("pagination", {})
            pages = pagination.get("pages", 1)

            if page >= pages:
                break

            page += 1
            sleep(1)


    return releases


# -----------------------------
# Session state, zooi in cache opslaan want sneller
# -----------------------------
if "df" not in st.session_state:
    st.session_state.df = None

if "usernames" not in st.session_state:
    st.session_state.usernames = []


headers = {}

top_col1, top_col2 = st.columns([2, 2])

with top_col1:
    run = st.button("Compare Collections")

with top_col2:
    download_placeholder = st.empty()


usernames = [
    u.strip()
    for u in usernames_text.splitlines()
    if u.strip()
]


# -----------------------------
# Main execution
# -----------------------------
if run:

    if not token:
        st.error("Please enter a Discogs API token.")
        st.stop()

    if len(usernames) < 2:
        st.error("Please enter at least two usernames.")
        st.stop()

    headers = {
        "Authorization": f"Discogs token={token}",
        "User-Agent": "DiscogsCollectionComparator/1.0"
    }

    progress = st.progress(0)
    collections = {}

    try:
        for i, username in enumerate(usernames):

            st.write(f"Fetching **{username}**...")

            collections[username] = get_collection(username, headers)

            progress.progress((i + 1) / len(usernames))

        all_releases = {}

        for username, releases in collections.items():

            for release in releases:

                release_id = release["release_id"]

                if release_id not in all_releases:

                    all_releases[release_id] = {
                        "Release ID": release_id,
                        "Artist": release["artist"],
                        "Title": release["title"],
                        "Thumb": release["thumb"]
                    }

                all_releases[release_id][username] = True

        rows = []

        for release in all_releases.values():

            row = release.copy()

            for username in usernames:
                row.setdefault(username, False)

            rows.append(row)

        df = pd.DataFrame(rows)
        df = df.sort_values(["Artist", "Title"]).reset_index(drop=True)

        st.session_state.df = df
        st.session_state.usernames = usernames

        st.success("Collections compared successfully!")

    except Exception as e:
        st.error(str(e))


# -----------------------------
# Output section
# -----------------------------
df = st.session_state.df

if df is not None and len(st.session_state.usernames) > 0:

    usernames = st.session_state.usernames

    csv_df = df.copy()

    for user in usernames:
        csv_df[user] = csv_df[user].map(lambda x: "TRUE" if x else "FALSE")

    csv_df = csv_df.drop(columns=["Thumb"])

    csv = csv_df.to_csv(index=False).encode("utf-8")

    download_placeholder.download_button(
        "📥 Download CSV",
        csv,
        "discogs_collection_comparison.csv",
        "text/csv"
    )

    st.divider()

    shared_df = df[df[usernames].all(axis=1)]

    col1, col2, col3 = st.columns(3)

    with col1:
        st.metric("Total Unique Releases", len(df))

    with col2:
        st.metric("Shared By Everyone", len(shared_df))

    with col3:
        st.metric("Users Compared", len(usernames))

    st.subheader("📚 Collection Sizes")

    summary_df = pd.DataFrame({
        "User": usernames,
        "Releases": [int(df[user].sum()) for user in usernames]
    })

    st.bar_chart(summary_df.set_index("User"))

    st.subheader("Collection Overlap")

    overlap = pd.DataFrame(index=usernames, columns=usernames)

    for user1 in usernames:

        releases1 = set(df[df[user1]]["Release ID"])

        for user2 in usernames:

            releases2 = set(df[df[user2]]["Release ID"])

            intersection = len(releases1 & releases2)
            union = len(releases1 | releases2)

            overlap.loc[user1, user2] = (
                f"{round((intersection / union) * 100, 1)}%"
                if union else "0%"
            )

    st.dataframe(overlap, use_container_width=True)

    st.subheader("Exclusive Releases")

    selected_user = st.selectbox("Show releases owned only by:", usernames)

    exclusive_df = df[
        (df[selected_user]) &
        (df[usernames].sum(axis=1) == 1)
    ]

    st.metric("Exclusive Releases", len(exclusive_df))

    with st.expander("View Exclusive Releases"):
        st.dataframe(exclusive_df[["Artist", "Title"]], use_container_width=True)

    st.subheader("🎯 Shared Releases")

    st.metric("Owned By Everyone", len(shared_df))

    with st.expander("View Shared Releases"):
        st.dataframe(shared_df[["Artist", "Title"]], use_container_width=True)

    st.subheader("💿 Releases")

    search = st.text_input("Search artist or title", value="", label_visibility="collapsed")

    filtered_df = df.copy()

    if search:
        filtered_df = filtered_df[
            filtered_df["Artist"].str.contains(search, case=False, na=False)
            | filtered_df["Title"].str.contains(search, case=False, na=False)
        ]

    st.write(f"Showing {len(filtered_df):,} releases")

    max_cards = 500

    for _, row in filtered_df.head(max_cards).iterrows():

        owners = [user for user in usernames if row[user]]

        c1, c2 = st.columns([1, 5])

        with c1:
            if row["Thumb"]:
                st.image(row["Thumb"], width=90)

        with c2:
            st.markdown(f"### {row['Title']}")
            st.caption(row["Artist"])
            st.write("👥 " + ", ".join(owners))
            st.progress(len(owners) / len(usernames))

    if len(filtered_df) > max_cards:
        st.info(f"Displaying first {max_cards} releases.")
