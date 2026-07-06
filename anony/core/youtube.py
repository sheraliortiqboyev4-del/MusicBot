# Copyright (c) 2025 AnonymousX1025
# Licensed under the MIT License.
# This file is part of AnonXMusic


import os
import re
import yt_dlp
import random
import asyncio
import aiohttp
from pathlib import Path

from py_yt import Playlist, VideosSearch

from anony import logger
from anony.helpers import Track, utils


class YouTube:
    def __init__(self):
        self.base = "https://www.youtube.com/watch?v="
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

    async def download(self, video_id: str, video: bool = False) -> str | None:
        url = self.base + video_id
        ext = "mp4" if video else "webm"
        filename = f"downloads/{video_id}.{ext}"

        if Path(filename).exists():
            return filename

        cookie = self.get_cookies()

        # Try primary format first
        if video:
            primary_opts = {
                "outtmpl": "downloads/%(id)s.%(ext)s",
                "quiet": True,
                "noplaylist": True,
                "geo_bypass": True,
                "no_warnings": True,
                "overwrites": False,
                "nocheckcertificate": True,
                "cookiefile": cookie,
                "format": "(bestvideo[height<=?720][width<=?1280][ext=mp4])+(bestaudio)",
                "merge_output_format": "mp4",
            }
            # Fallback format for video
            fallback_opts = {
                "outtmpl": "downloads/%(id)s.%(ext)s",
                "quiet": True,
                "noplaylist": True,
                "geo_bypass": True,
                "no_warnings": True,
                "overwrites": False,
                "nocheckcertificate": True,
                "cookiefile": cookie,
                "format": "best[ext=mp4][height<=?720]",
            }
        else:
            primary_opts = {
                "outtmpl": "downloads/%(id)s.%(ext)s",
                "quiet": True,
                "noplaylist": True,
                "geo_bypass": True,
                "no_warnings": True,
                "overwrites": False,
                "nocheckcertificate": True,
                "cookiefile": cookie,
                "format": "bestaudio[ext=webm][acodec=opus]",
            }
            # Fallback formats for audio
            fallback_opts_list = [
                {
                    **primary_opts,
                    "format": "bestaudio[ext=m4a]",
                },
                {
                    **primary_opts,
                    "format": "bestaudio",
                },
            ]

        def _download():
            # First try primary format
            with yt_dlp.YoutubeDL(primary_opts) as ydl:
                try:
                    ydl.download([url])
                    return filename
                except Exception as ex:
                    logger.warning("Primary download failed: %s, trying fallbacks", ex)
                    
            # If video, try fallback format
            if video:
                with yt_dlp.YoutubeDL(fallback_opts) as ydl:
                    try:
                        ydl.download([url])
                        return filename
                    except Exception as ex:
                        logger.warning("Video fallback download failed: %s", ex)
                        return None
            else:
                # If audio, try all fallback formats
                for opts in fallback_opts_list:
                    with yt_dlp.YoutubeDL(opts) as ydl:
                        try:
                            ydl.download([url])
                            # Check what file was downloaded
                            for f in Path("downloads").iterdir():
                                if f.stem == video_id and f.is_file():
                                    return str(f)
                        except Exception as ex:
                            logger.warning("Fallback download failed: %s", ex)
                            continue
                return None

        result = await asyncio.to_thread(_download)
        
        # Also try without cookies if all else fails
        if not result:
            logger.info("Trying download without cookies...")
            
            def _download_no_cookies():
                opts = {
                    "outtmpl": "downloads/%(id)s.%(ext)s",
                    "quiet": True,
                    "noplaylist": True,
                    "geo_bypass": True,
                    "no_warnings": True,
                    "overwrites": False,
                    "nocheckcertificate": True,
                    "format": "bestaudio" if not video else "best[height<=?720]",
                }
                with yt_dlp.YoutubeDL(opts) as ydl:
                    try:
                        ydl.download([url])
                        for f in Path("downloads").iterdir():
                            if f.stem == video_id and f.is_file():
                                return str(f)
                    except Exception as ex:
                        logger.warning("No-cookie download failed: %s", ex)
                        return None
            
            result = await asyncio.to_thread(_download_no_cookies)
        
        return result
