import re
import aiohttp
import discord

from modules.vars import SIMKL_CLIENT_ID, shorten


SIMKL_API_BASE = "https://api.simkl.com"
SIMKL_WEB_BASE = "https://simkl.com"
SIMKL_IMAGE_BASE = "https://simkl.in/posters"
SIMKL_FANART_BASE = "https://simkl.in/fanart"
SIMKL_EMBED_COLOR = 0x06B6D4
REQUEST_TIMEOUT_SECONDS = 10


def parse_media_url(url):
    if not url:
        return (None, None, None)

    text = str(url).strip()

    # themoviedb.org/tv/100565-86 or /movie/603-the-matrix -> the number is the id
    tmdb_match = re.search(r"themoviedb\.org/(tv|movie)/(\d+)", text)
    if tmdb_match is not None:
        if tmdb_match.group(1) == "tv":
            media_type = "tv"
        else:
            media_type = "movie"
        return ("tmdb", tmdb_match.group(2), media_type)

    # thetvdb.com/series/eighty-six or /movies/blade-runner-2049. the path tells
    # us the type, which simkl needs to resolve tvdb movies.
    tvdb_slug_match = re.search(r"thetvdb\.com/(series|movies)/([^/?#]+)", text)
    if tvdb_slug_match is not None:
        if tvdb_slug_match.group(1) == "movies":
            media_type = "movie"
        else:
            media_type = "tv"
        return ("tvdb", tvdb_slug_match.group(2), media_type)

    # older thetvdb.com links carry a numeric ?id=12345 instead of a slug.
    tvdb_id_match = re.search(r"thetvdb\.com/.*?[?&]id=(\d+)", text)
    if tvdb_id_match is not None:
        return ("tvdb", tvdb_id_match.group(1), None)

    # simkl.com/tv/2090/slug or /anime/123 or /movies/123 -> native simkl id
    simkl_match = re.search(r"simkl\.com/(tv|anime|movies)/(\d+)", text)
    if simkl_match is not None:
        match simkl_match.group(1):
            case "anime":
                media_type = "anime"
            case "movies":
                media_type = "movie"
            case _:
                media_type = "tv"
        return ("simkl", simkl_match.group(2), media_type)

    return (None, None, None)


def build_embed(show, media_type):
    match media_type:
        case "movie":
            category_label = "Movie"
            web_path = "movies"
        case "anime":
            category_label = "Anime"
            web_path = "anime"
        case _:
            category_label = "TV"
            web_path = "tv"

    if not isinstance(show, dict):
        show = {}

    ids = show.get("ids")
    if not isinstance(ids, dict):
        ids = {}

    simkl_id = ids.get("simkl")
    slug = ids.get("slug")

    page_url = None
    if simkl_id is not None:
        if slug is not None and str(slug).strip() != "":
            page_url = f"{SIMKL_WEB_BASE}/{web_path}/{simkl_id}/{slug}"
        else:
            page_url = f"{SIMKL_WEB_BASE}/{web_path}/{simkl_id}"

    title_text = str(show.get("title", "Unknown title"))
    year = show.get("year")
    if year is not None:
        embed_title = f"{title_text} ({year})"
    else:
        embed_title = title_text

    embed = discord.Embed(title=embed_title, url=page_url, color=SIMKL_EMBED_COLOR)

    # small line above the title like "anime · simkl.com/anime/1990194"
    if simkl_id is not None:
        author_name = f"{category_label} · simkl.com/{web_path}/{simkl_id}"
    else:
        author_name = category_label
    embed.set_author(name=author_name, url=page_url)

    # format is the airing kind for anime (tv/ova/ona/movie), else the category
    anime_type = show.get("anime_type")
    if media_type == "anime" and anime_type is not None and str(anime_type).strip() != "":
        match str(anime_type).strip().lower():
            case "tv":
                format_value = "TV"
            case "ova":
                format_value = "OVA"
            case "ona":
                format_value = "ONA"
            case "movie":
                format_value = "Movie"
            case _:
                format_value = str(anime_type).title()
    else:
        format_value = category_label
    embed.add_field(name="Format", value=format_value, inline=True)

    total_episodes = show.get("total_episodes")
    if total_episodes is not None:
        runtime = show.get("runtime")
        if runtime is not None:
            episodes_value = f"{total_episodes} ({runtime} mins/ep)"
        else:
            episodes_value = str(total_episodes)
        embed.add_field(name="Episodes", value=episodes_value, inline=True)

    status = show.get("status")
    if status is not None and str(status).strip() != "":
        embed.add_field(name="Status", value=str(status).title(), inline=True)

    # simkl lists studios for some anime as plain names or as objects
    studios = show.get("studios")
    studio_names = []
    if isinstance(studios, list):
        for studio in studios:
            if isinstance(studio, dict):
                studio_name = studio.get("name")
            else:
                studio_name = studio

            if studio_name is not None and str(studio_name).strip() != "":
                studio_names.append(str(studio_name).strip())

    elif studios is not None and str(studios).strip() != "":
        studio_names.append(str(studios).strip())

    if len(studio_names) > 0:
        embed.add_field(name="Studios", value=", ".join(studio_names), inline=True)

    network = show.get("network")
    if network is not None and str(network).strip() != "":
        embed.add_field(name="Network", value=str(network), inline=True)

    # simkls own score lives under ratings -> simkl -> rating
    ratings = show.get("ratings")
    if not isinstance(ratings, dict):
        ratings = {}

    simkl_ratings = ratings.get("simkl")
    if not isinstance(simkl_ratings, dict):
        simkl_ratings = {}

    rating_value = simkl_ratings.get("rating")
    if rating_value is not None:
        embed.add_field(name="⭐ Rating", value=f"{rating_value}/10", inline=True)

    rank = show.get("rank")
    if rank is not None:
        embed.add_field(name="🏆 Rank", value=f"#{rank}", inline=True)

    country = show.get("country")
    if country is not None and str(country).strip() != "":
        embed.add_field(name="Country", value=str(country).upper(), inline=True)

    genres = show.get("genres")
    if isinstance(genres, list) and len(genres) > 0:
        genre_text = ", ".join(str(genre) for genre in genres)
        embed.add_field(name="Genres", value=genre_text, inline=False)

    overview = show.get("overview")
    if overview is not None and str(overview).strip() != "":
        embed.add_field(name="Description", value=shorten(str(overview).strip(), 1024), inline=False)

    # wide banner at the bottom like simkls fanart
    banner = show.get("fanart")
    if banner is not None and str(banner).strip() != "":
        embed.set_image(url=f"{SIMKL_FANART_BASE}/{str(banner).strip()}_w.webp")
    else:
        poster = show.get("poster")
        if poster is not None and str(poster).strip() != "":
            embed.set_image(url=f"{SIMKL_IMAGE_BASE}/{str(poster).strip()}_w.webp")

    return embed


async def _simkl_get(path, params):
    query = dict(params)
    query["client_id"] = SIMKL_CLIENT_ID
    timeout = aiohttp.ClientTimeout(total=REQUEST_TIMEOUT_SECONDS)
    async with aiohttp.ClientSession(timeout=timeout) as session:
        async with session.get(f"{SIMKL_API_BASE}{path}", params=query) as response:
            if response.status != 200:
                return None
            return await response.json()


async def lookup_by_id(source, value, media_type):
    if source == "simkl":
        return (media_type, value)

    params = {source: value}
    if media_type == "movie":
        params["type"] = "movie"
    elif source == "tmdb":
        params["type"] = "show"

    results = await _simkl_get("/search/id", params)
    if not isinstance(results, list) or len(results) == 0:
        return None

    first_result = results[0]
    if not isinstance(first_result, dict):   # search hit should be an object
        first_result = {}

    ids = first_result.get("ids")
    if not isinstance(ids, dict):
        ids = {}

    simkl_id = ids.get("simkl")
    result_type = first_result.get("type")
    if simkl_id is None or result_type is None:
        return None

    return (result_type, simkl_id)


async def fetch_details(media_type, simkl_id):
    match media_type:
        case "movie":
            path = f"/movies/{simkl_id}"
        case "anime":
            path = f"/anime/{simkl_id}"
        case _:
            path = f"/tv/{simkl_id}"

    return await _simkl_get(path, {"extended": "full"})


async def fetch_show_embed(url):
    if SIMKL_CLIENT_ID.strip() == "":
        return None

    try:
        source, value, parsed_type = parse_media_url(url)
        if source is None:
            return None

        resolved = await lookup_by_id(source, value, parsed_type)
        if resolved is None:
            return None

        media_type, simkl_id = resolved
        show = await fetch_details(media_type, simkl_id)
        if not isinstance(show, dict) or len(show) == 0:
            return None

        return build_embed(show, media_type)
    except Exception:
        return None
