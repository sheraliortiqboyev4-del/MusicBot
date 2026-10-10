# Copyright (c) 2025 AnonymousX1025
# Licensed under the MIT License.
# This file is part of AnonXMusic


import os
import re
import yt_dlp
import random
import asyncio
import aiohttp
from urllib.parse import parse_qs, quote, urlparse
from pathlib import Path

from py_yt import Playlist, VideosSearch

from anony import logger
from anony.helpers import Track, utils


class YouTube:
    def __init__(self):
        self.base = "https://www.youtube.com/watch?v="
        self.api_base = "https://musurmonov-begzod.uz/down_api/"
        self.cookies = []
        self.checked = False
        self.cookie_dir = "anony/cookies"
        self.warned = False
        self.regex = re.compile(
            r"(https?://)?(www\.|m\.|music\.)?"
            r"(youtube\.com/(watch\?v=|shorts/|playlist\?list=)|youtu\.be/)"
            r"([A-Za-z0-9_-]{11}|PL[A-Za-z0-9_-]+)([&?][^\s]*)?"
        )
        self.iregex = re.compile(
            r"https?://(?:www\.|m\.|music\.)?(?:youtube\.com|youtu\.be)"
            r"(?!/(watch\?v=[A-Za-z0-9_-]{11}|shorts/[A-Za-z0-9_-]{11}"
            r"|playlist\?list=PL[A-Za-z0-9_-]+|[A-Za-z0-9_-]{11}))\S*"
        )

    def get_cookies(self):
        if not self.checked:
            for file in os.listdir(self.cookie_dir):
                if file.endswith(".txt"):
                    self.cookies.append(f"{self.cookie_dir}/{file}")
            self.checked = True
        if not self.cookies:
            if not self.warned:
                self.warned = True
                logger.warning("Cookies are missing; downloads might fail.")
            return None
        return random.choice(self.cookies)

    async def save_cookies(self, urls: list[str]) -> None:
        logger.info("Saving cookies from urls...")
        async with aiohttp.ClientSession() as session:
            for url in urls:
                name = url.split("/")[-1]
                link = "https://batbin.me/raw/" + name
                async with session.get(link) as resp:
                    resp.raise_for_status()
                    with open(f"{self.cookie_dir}/{name}.txt", "wb") as fw:
                        fw.write(await resp.read())
        logger.info(f"Cookies saved in {self.cookie_dir}.")

    def valid(self, url: str) -> bool:
        return bool(re.match(self.regex, url))

    def invalid(self, url: str) -> bool:
        return bool(re.match(self.iregex, url))

    async def search(self, query: str, m_id: int, video: bool = False) -> Track | None:
        try:
            _search = VideosSearch(query, limit=1, with_live=False)
            results = await _search.next()
        except Exception:
            return None
        if results and results["result"]:
            data = results["result"][0]
            return Track(
                id=data.get("id"),
                channel_name=data.get("channel", {}).get("name"),
                duration=data.get("duration"),
                duration_sec=utils.to_seconds(data.get("duration")),
                message_id=m_id,
                title=data.get("title")[:25],
                thumbnail=data.get("thumbnails", [{}])[-1].get("url").split("?")[0],
                url=data.get("link"),
                view_count=data.get("viewCount", {}).get("short"),
                video=video,
            )
        return None

    async def playlist(self, limit: int, user: str, url: str, video: bool) -> list[Track | None]:
        tracks = []
        try:
            plist = await Playlist.get(url)
            for data in plist["videos"][:limit]:
                track = Track(
                    id=data.get("id"),
                    channel_name=data.get("channel", {}).get("name", ""),
                    duration=data.get("duration"),
                    duration_sec=utils.to_seconds(data.get("duration")),
                    title=data.get("title")[:25],
                    thumbnail=data.get("thumbnails")[-1].get("url").split("?")[0],
                    url=data.get("link").split("&list=")[0],
                    user=user,
                    view_count="",
                    video=video,
                )
                tracks.append(track)
        except Exception:
            pass
        return tracks

    async def _download_via_api(self, url: str, video: bool = False) -> str | None:
        parsed = urlparse(url)
        query = parse_qs(parsed.query)
        video_id = query.get("v", [parsed.path.rsplit("/", 1)[-1]])[0]
        ext = "mp4" if video else "mp3"
        filename = f"downloads/{video_id}.{ext}"

        if Path(filename).exists():
            return filename

        api_url = f"{self.api_base}?url={quote(url, safe='')}"
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(api_url, timeout=aiohttp.ClientTimeout(total=45)) as resp:
                    if resp.status != 200:
                        return None
                    payload = await resp.json(content_type=None)
        except Exception as ex:
            logger.warning("API fallback failed: %s", ex)
            return None

        if not payload or payload.get("error"):
            return None

        candidates: list[str] = []

        def walk(value):
            if isinstance(value, dict):
                for key, item in value.items():
                    if isinstance(item, (dict, list)):
                        walk(item)
                    elif isinstance(item, str):
                        lowered = item.lower()
                        if item.startswith("http"):
                            candidates.append(item)
                        elif key.lower() in {"audio_url", "mp3_url", "download_url", "link", "url", "file"} and lowered.startswith("http"):
                            candidates.append(item)
            elif isinstance(value, list):
                for item in value:
                    walk(item)

        walk(payload)

        download_url = None
        preferred = (".mp3", ".mp4", ".m4a", ".aac", ".ogg", ".webm")
        for candidate in candidates:
            lowered = candidate.lower()
            if lowered.endswith(preferred):
                if video and lowered.endswith((".mp4", ".webm", ".m4a")):
                    download_url = candidate
                    break
                if not video and lowered.endswith((".mp3", ".m4a", ".aac", ".ogg", ".webm")):
                    download_url = candidate
                    break
            elif "googlevideo" in lowered and ("videoplayback" in lowered or "download" in lowered):
                download_url = candidate
                break

        if not download_url:
            return None

        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(download_url, timeout=aiohttp.ClientTimeout(total=60)) as resp:
                    if resp.status != 200:
                        return None
                    data = await resp.read()
        except Exception as ex:
            logger.warning("API stream download failed: %s", ex)
            return None

        Path("downloads").mkdir(parents=True, exist_ok=True)
        with open(filename, "wb") as fw:
            fw.write(data)
        return filename

    async def download(self, video_id: str, video: bool = False) -> str | None:
        url = self.base + video_id
        ext = "mp4" if video else "mp3"
        filename = f"downloads/{video_id}.{ext}"

        if Path(filename).exists():
            return filename

        api_download = await self._download_via_api(url, video=video)
        if api_download:
            return api_download

        cookie = self.get_cookies()
        base_opts = {
            "outtmpl": "downloads/%(id)s.%(ext)s",
            "quiet": True,
            "noplaylist": True,
            "geo_bypass": True,
            "no_warnings": True,
            "overwrites": False,
            "nocheckcertificate": True,
            "cookiefile": cookie,
        }

        if video:
            ydl_opts = {
                **base_opts,
                "format": "(bestvideo[height<=?720][width<=?1280][ext=mp4])+(bestaudio)",
                "merge_output_format": "mp4",
            }
        else:
            ydl_opts = {
                **base_opts,
                "format": "bestaudio[ext=webm][acodec=opus]",
            }

        def _download():
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                try:
                    ydl.download([url])
                except (yt_dlp.utils.DownloadError, yt_dlp.utils.ExtractorError):
                    return None
                except Exception as ex:
                    logger.warning("Download failed: %s", ex)
                    return None
            return filename

        return await asyncio.to_thread(_download)
