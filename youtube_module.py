import base64
import os
import re
import shutil
import subprocess
import tempfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Dict, List, Optional, Tuple
from urllib.parse import parse_qs, urlparse

import yt_dlp
from openai import OpenAI

# ---------------------------------------------------------------------------
# 常數設定
# ---------------------------------------------------------------------------

# OpenAI Whisper 單檔上限為 25MB，留一點安全邊界
WHISPER_MAX_BYTES = 24 * 1024 * 1024

# 轉檔給 Whisper 使用的音訊參數（單聲道 16kHz 足夠語音辨識，檔案極小）
WHISPER_SAMPLE_RATE = 16000
WHISPER_BITRATE_KBPS = 32

# 可接受的最長影片長度（秒），預設 4 小時，可用環境變數覆寫
DEFAULT_MAX_DURATION_SECONDS = 4 * 60 * 60

# 長音檔切段並行轉錄：Whisper 的耗時與音檔長度成正比，
# 切成小段同時送出可以大幅縮短長影片的等待時間。
PARALLEL_CHUNK_SECONDS = 300          # 每段 5 分鐘
PARALLEL_MIN_DURATION_SECONDS = 600   # 超過 10 分鐘才值得切段
DEFAULT_TRANSCRIBE_WORKERS = 4

_YOUTUBE_HOSTS = {
    "youtube.com",
    "m.youtube.com",
    "music.youtube.com",
    "gaming.youtube.com",
    "youtu.be",
    "youtube-nocookie.com",
}

_MEDIA_EXTENSIONS = (
    ".m4a",
    ".webm",
    ".mp3",
    ".opus",
    ".mp4",
    ".mka",
    ".aac",
    ".ogg",
    ".wav",
    ".flac",
    ".3gp",
)

# 當預設抽取流程被 YouTube 擋下時，依序改用這些 innertube client 重試。
# 這些 client 在資料中心 IP（例如 Cloud Run）上通常較不容易被要求登入驗證。
_DEFAULT_CLIENT_FALLBACKS = (
    "tv_simply",
    "android_vr",
    "visionos",
    "ios",
    "mweb",
    "web_safari",
    "tv",
    "web_embedded",
)


# ---------------------------------------------------------------------------
# URL 解析
# ---------------------------------------------------------------------------


def _is_video_id(value: Optional[str]) -> bool:
    return bool(value) and re.fullmatch(r"[A-Za-z0-9_-]{11}", value) is not None


def extract_video_id(url: str) -> Optional[str]:
    """從各種 YouTube URL 形式中提取影片 ID

    支援：watch?v=、shorts/、live/、embed/、v/、youtu.be/，
    以及 m.youtube.com、music.youtube.com 等子網域。
    """
    if not url or not url.strip():
        return None

    raw = url.strip()
    if not re.match(r"^[a-zA-Z][a-zA-Z0-9+.-]*://", raw):
        raw = "https://" + raw

    try:
        parsed = urlparse(raw)
    except ValueError:
        return None

    host = (parsed.hostname or "").lower()
    if host.startswith("www."):
        host = host[4:]
    if host not in _YOUTUBE_HOSTS:
        return None

    # https://youtu.be/<id>
    if host == "youtu.be":
        segments = [s for s in parsed.path.split("/") if s]
        return segments[0] if segments and _is_video_id(segments[0]) else None

    # https://www.youtube.com/watch?v=<id>
    if parsed.path.rstrip("/") in ("/watch", "/watch_popup"):
        candidate = parse_qs(parsed.query).get("v", [None])[0]
        return candidate if _is_video_id(candidate) else None

    # https://www.youtube.com/{shorts,live,embed,v,shorts}/<id>
    match = re.match(r"^/(?:shorts|live|embed|v)/([A-Za-z0-9_-]+)", parsed.path)
    if match and _is_video_id(match.group(1)):
        return match.group(1)

    return None


def is_valid_youtube_url(url: str) -> bool:
    """檢查是否為可處理的 YouTube URL（一般影片、Shorts、直播回放皆可）"""
    return extract_video_id(url) is not None


# ---------------------------------------------------------------------------
# ffmpeg 工具
# ---------------------------------------------------------------------------


def clean_description(text: str, limit: int = 1500) -> str:
    """清掉 YouTube 說明欄的雜訊，保留有資訊價值的內容

    說明欄常常同時包含兩種東西：
    - 有用的：本集造訪的店家清單、地址、時間軸章節名稱
    - 沒用的：連結、訂閱/合作聯繫、社群帳號、大量 hashtag
    這裡把後者濾掉，讓地點抽取能吃到店名與章節名稱。
    """
    if not text:
        return ""

    noise_markers = (
        "http://", "https://", "www.",
        "訂閱", "追蹤", "合作邀約", "業配", "工商", "來信", "洽詢",
        "instagram", "facebook", "twitter", "tiktok", "discord",
        "subscribe", "follow me", "business", "sponsor",
    )

    kept = []
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            continue

        lowered = line.lower()
        if any(marker in lowered for marker in noise_markers):
            # 章節時間軸這類「時間 + 地點」的行即使含連結也要留，
            # 但整行就是連結或聯絡資訊時直接丟掉
            stripped = re.sub(r"https?://\S+|www\.\S+", "", line).strip()
            if len(stripped) < 4:
                continue
            line = stripped
            if any(marker in line.lower() for marker in noise_markers[3:]):
                continue

        # 一整行都是 hashtag 就沒有敘述價值
        tokens = line.split()
        if tokens and all(t.startswith("#") for t in tokens):
            continue

        kept.append(line)
        if sum(len(k) for k in kept) > limit:
            break

    cleaned = "\n".join(kept).strip()
    return cleaned[:limit]


def _ffmpeg_path() -> Optional[str]:
    return shutil.which("ffmpeg")


def _ffprobe_path() -> Optional[str]:
    return shutil.which("ffprobe")


def _run_command(cmd: List[str], timeout: int) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)


def _probe_duration(path: str) -> float:
    """用 ffprobe 取得音檔長度（秒），失敗時回傳 0"""
    ffprobe = _ffprobe_path()
    if not ffprobe:
        return 0.0
    try:
        result = _run_command(
            [
                ffprobe,
                "-v",
                "error",
                "-show_entries",
                "format=duration",
                "-of",
                "default=noprint_wrappers=1:nokey=1",
                path,
            ],
            timeout=60,
        )
        if result.returncode == 0:
            return float(result.stdout.strip())
    except Exception:
        pass
    return 0.0


def _transcode_for_whisper(source_path: str, workdir: str) -> str:
    """將任意音／視訊檔轉成 Whisper 友善的單聲道低位元率 mp3

    這一步同時解決三件事：
    1. 去除視訊軌，避免 mp4/webm 整包上傳
    2. 大幅縮小檔案，讓長影片也能落在 Whisper 的 25MB 限制內
    3. 統一容器格式，避免 DASH m4a 這類播放相容性問題
    """
    ffmpeg = _ffmpeg_path()
    if not ffmpeg:
        print("⚠️ 找不到 ffmpeg，直接使用原始音檔（長影片可能超過 Whisper 上限）")
        return source_path

    duration = _probe_duration(source_path)
    # 轉檔時間大致與長度成正比，給足夠寬鬆的 timeout
    timeout = max(300, int(duration * 2) + 120)

    target = os.path.join(workdir, "whisper_audio.mp3")
    print(f"🎛️ 轉檔為 Whisper 音訊格式（單聲道 {WHISPER_SAMPLE_RATE}Hz {WHISPER_BITRATE_KBPS}kbps）...")

    try:
        result = _run_command(
            [
                ffmpeg,
                "-y",
                "-i",
                source_path,
                "-vn",
                "-ac",
                "1",
                "-ar",
                str(WHISPER_SAMPLE_RATE),
                "-c:a",
                "libmp3lame",
                "-b:a",
                f"{WHISPER_BITRATE_KBPS}k",
                target,
            ],
            timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        print("⚠️ 轉檔逾時，改用原始音檔")
        return source_path
    except Exception as exc:
        print(f"⚠️ 轉檔失敗（{exc}），改用原始音檔")
        return source_path

    if result.returncode != 0 or not os.path.exists(target) or os.path.getsize(target) == 0:
        print(f"⚠️ 轉檔失敗，改用原始音檔: {result.stderr[-500:] if result.stderr else ''}")
        return source_path

    before = os.path.getsize(source_path) / 1024 / 1024
    after = os.path.getsize(target) / 1024 / 1024
    print(f"✅ 轉檔完成: {before:.1f}MB → {after:.1f}MB")
    return target


def _split_audio(path: str, workdir: str) -> List[str]:
    """把音檔切成多段

    兩種情況需要切段：
    1. 檔案超過 Whisper 單檔上限（否則會被 API 拒絕）
    2. 影片夠長 —— 切小段後可以並行轉錄，大幅縮短等待時間
    """
    size = os.path.getsize(path)
    duration = _probe_duration(path)

    over_size_limit = size > WHISPER_MAX_BYTES
    worth_parallelising = duration > PARALLEL_MIN_DURATION_SECONDS

    if not over_size_limit and not worth_parallelising:
        return [path]

    ffmpeg = _ffmpeg_path()
    if not ffmpeg or duration <= 0:
        if over_size_limit:
            print("⚠️ 音檔超過 Whisper 上限但無法切割（缺少 ffmpeg 或長度未知）")
        return [path]

    chunk_seconds = PARALLEL_CHUNK_SECONDS
    if over_size_limit:
        bytes_per_second = size / duration
        # 每段抓上限的 90%，避免邊界誤差
        size_limited = max(60, int((WHISPER_MAX_BYTES * 0.9) / bytes_per_second))
        chunk_seconds = min(chunk_seconds, size_limited)

    expected_chunks = int(duration // chunk_seconds) + 1
    reason = "超過 Whisper 上限" if over_size_limit else "長度較長，切段並行轉錄"

    print(
        f"✂️ 音檔 {size / 1024 / 1024:.1f}MB / {int(duration)}秒 {reason}，"
        f"切成約 {expected_chunks} 段（每段 {chunk_seconds} 秒）..."
    )

    chunk_dir = os.path.join(workdir, "chunks")
    os.makedirs(chunk_dir, exist_ok=True)
    pattern = os.path.join(chunk_dir, "chunk_%04d" + os.path.splitext(path)[1])

    try:
        result = _run_command(
            [
                ffmpeg,
                "-y",
                "-i",
                path,
                "-f",
                "segment",
                "-segment_time",
                str(chunk_seconds),
                "-c",
                "copy",
                pattern,
            ],
            timeout=max(600, int(duration) + 120),
        )
    except Exception as exc:
        print(f"⚠️ 切割音檔失敗: {exc}")
        return [path]

    chunks = sorted(
        os.path.join(chunk_dir, name)
        for name in os.listdir(chunk_dir)
        if name.startswith("chunk_")
    )

    if result.returncode != 0 or not chunks:
        print(f"⚠️ 切割音檔失敗: {result.stderr[-500:] if result.stderr else ''}")
        return [path]

    print(f"✅ 已切成 {len(chunks)} 段")
    return chunks


def _transcribe_workers() -> int:
    try:
        return max(1, int(os.getenv("WHISPER_PARALLEL_WORKERS", DEFAULT_TRANSCRIBE_WORKERS)))
    except ValueError:
        return DEFAULT_TRANSCRIBE_WORKERS


def _transcribe_file(client: OpenAI, path: str, context: str = "") -> str:
    """對單一音檔呼叫 Whisper，含簡單重試

    context 會作為 Whisper 的 prompt：提供影片標題／說明欄片段，
    可以大幅改善專有名詞（店名、地名）的轉寫正確率，
    例如「澀谷橫丁」不會被寫成「澀谷橫濱」。
    """
    last_error = None
    for attempt in range(1, 3):
        try:
            with open(path, "rb") as handle:
                params = {
                    "model": "whisper-1",
                    "file": handle,
                    "response_format": "text",
                    "temperature": 0.0,
                }
                if context:
                    params["prompt"] = context[:800]
                response = client.audio.transcriptions.create(**params)
            return response.strip()
        except Exception as exc:
            last_error = exc
            print(f"⚠️ Whisper 轉錄失敗（第 {attempt} 次）: {exc}")
    if last_error:
        print(f"❌ 放棄此段落轉錄: {last_error}")
    return ""


def audio_to_text(video_path: str, context: str = "") -> str:
    """使用 Whisper 將音訊轉為文字

    會先轉成低位元率單聲道 mp3；若仍超過 Whisper 的 25MB 上限，
    則自動切段轉錄再合併，讓長影片也能完整轉錄。
    """
    workdir = None
    try:
        if not os.path.exists(video_path):
            raise FileNotFoundError(f"音頻檔案不存在: {video_path}")

        file_size = os.path.getsize(video_path)
        print(f"🎵 音頻檔案大小: {file_size / 1024 / 1024:.1f}MB")
        if file_size == 0:
            raise Exception("音頻檔案為空")

        workdir = tempfile.mkdtemp(prefix="whisper_")

        prepared = _transcode_for_whisper(video_path, workdir)
        chunks = _split_audio(prepared, workdir)

        client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

        print(f"🤖 使用 Whisper-1 進行語音轉文字（共 {len(chunks)} 段）...")

        if len(chunks) == 1:
            segments = [_transcribe_file(client, chunks[0], context)]
        else:
            workers = min(_transcribe_workers(), len(chunks))
            print(f"   ⚡ 以 {workers} 條並行轉錄")
            # 保持段落順序，否則逐字稿會錯亂
            segments = [""] * len(chunks)
            with ThreadPoolExecutor(max_workers=workers) as pool:
                futures = {
                    pool.submit(_transcribe_file, client, chunk, context): index
                    for index, chunk in enumerate(chunks)
                }
                for future in as_completed(futures):
                    index = futures[future]
                    segments[index] = future.result()
                    print(f"   ▶ 第 {index + 1}/{len(chunks)} 段完成")

        transcription = " ".join(part for part in segments if part).strip()
        if transcription:
            print(f"✅ 語音轉文字成功，長度: {len(transcription)}字符")
            return transcription

        print("⚠️ Whisper返回空結果")
        return ""

    except Exception as exc:
        print(f"❌ 語音轉文字失敗: {exc}")
        return ""
    finally:
        if workdir:
            shutil.rmtree(workdir, ignore_errors=True)


# ---------------------------------------------------------------------------
# yt-dlp 下載
# ---------------------------------------------------------------------------


def _resolve_cookiefile(workdir: str) -> Optional[str]:
    """支援以檔案路徑或環境變數內容提供 YouTube cookies

    在資料中心 IP（Cloud Run）上，YouTube 常要求「確認你不是機器人」，
    帶上已登入的 cookies 是最有效的解法。
    """
    path = os.getenv("YTDLP_COOKIES_FILE")
    if path and os.path.exists(path):
        print(f"🍪 使用 cookies 檔案: {path}")
        return path

    # YTDLP_COOKIES 是既有部署已經掛上的名稱（來自 Secret Manager），
    # 內容可能是檔案路徑、Netscape 純文字或 base64，一律在這裡吸收。
    content = (
        os.getenv("YTDLP_COOKIES_CONTENT")
        or os.getenv("YTDLP_COOKIES")
        or ""
    )
    if content.strip() and os.path.exists(content.strip()):
        resolved = content.strip()
        print(f"🍪 使用 cookies 檔案: {resolved}")
        return resolved

    if content and content.strip():
        text = content.strip()
        # 允許直接貼 Netscape 格式，或為了塞進環境變數而做的 base64
        if not text.startswith("# Netscape") and "\t" not in text:
            try:
                text = base64.b64decode(text).decode("utf-8")
            except Exception:
                pass
        destination = os.path.join(workdir, "cookies.txt")
        with open(destination, "w", encoding="utf-8") as handle:
            handle.write(text if text.endswith("\n") else text + "\n")
        print("🍪 使用環境變數提供的 cookies")
        _mirror_google_cookies_to_youtube(destination)
        _report_cookie_health(destination)
        return destination

    return None


def _mirror_google_cookies_to_youtube(path: str) -> None:
    """把 .google.com 上的登入 cookie 補寫一份到 .youtube.com

    很多瀏覽器外掛匯出的 cookies 只帶到 google.com 網域，
    但 YouTube 判斷登入狀態看的是 youtube.com 上的 cookie。
    真實瀏覽器的這些 cookie 本來就同時存在於兩個網域且值相同，
    這裡只是把既有的值補上缺少的網域，不會產生任何新的憑證。
    """
    mirror_names = {
        "SID", "HSID", "SSID", "APISID", "SAPISID", "LOGIN_INFO", "SIDCC",
        "__Secure-1PSID", "__Secure-3PSID",
        "__Secure-1PAPISID", "__Secure-3PAPISID",
        "__Secure-1PSIDTS", "__Secure-3PSIDTS",
        "__Secure-1PSIDCC", "__Secure-3PSIDCC",
    }

    try:
        with open(path, encoding="utf-8", errors="replace") as handle:
            lines = handle.readlines()

        google_rows = {}
        youtube_names = set()

        for line in lines:
            stripped = line.strip()
            if not stripped or stripped.startswith("#"):
                continue
            parts = stripped.split("\t")
            if len(parts) < 7:
                continue
            domain = parts[0].lstrip(".").lower()
            name = parts[5]
            if domain.endswith("youtube.com"):
                youtube_names.add(name)
            elif domain.endswith("google.com") and name in mirror_names:
                # 同名 cookie 以第一次出現為準
                google_rows.setdefault(name, parts)

        missing = {n: r for n, r in google_rows.items() if n not in youtube_names}
        if not missing:
            return

        additions = []
        for name, parts in missing.items():
            row = list(parts)
            row[0] = ".youtube.com"
            row[1] = "TRUE"
            additions.append("\t".join(row))

        with open(path, "a", encoding="utf-8") as handle:
            handle.write("\n".join(additions) + "\n")

        print(
            f"🔧 已把 {len(additions)} 個 google.com 登入 cookie 補寫到 .youtube.com: "
            + ", ".join(sorted(missing))
        )
    except Exception as exc:
        print(f"⚠️ 補寫 youtube.com cookies 失敗: {exc}")


def _report_cookie_health(path: str) -> None:
    """記錄 cookies 的健康狀態（只輸出統計與到期時間，不輸出任何 cookie 值）

    YouTube 的 cookies 會過期，過期後 yt-dlp 會退回「Sign in to confirm
    you\u2019re not a bot」，看起來就像沒帶 cookies 一樣。
    這段記錄讓我們能直接從 log 判斷是不是該更新 cookies。
    """
    try:
        import time

        now = time.time()
        total = 0
        expired = 0
        domains = set()
        auth_names = set()
        # 依網域分開統計：YouTube 的登入判斷看的是 .youtube.com 上的 cookie，
        # 只匯出 google.com 的 cookie 會造成「有登入 cookie 卻仍被當成訪客」
        auth_by_domain = {}
        soonest = None

        with open(path, encoding="utf-8", errors="replace") as handle:
            for line in handle:
                line = line.rstrip("\n")
                if not line or line.startswith("#"):
                    continue
                parts = line.split("\t")
                if len(parts) < 7:
                    continue
                total += 1
                domains.add(parts[0].lstrip("."))
                name = parts[5]
                if name in {
                    "SID", "HSID", "SSID", "APISID", "SAPISID", "LOGIN_INFO",
                    "__Secure-1PSID", "__Secure-3PSID",
                }:
                    auth_names.add(name)
                    host = parts[0].lstrip(".")
                    auth_by_domain.setdefault(host, set()).add(name)
                try:
                    expiry = float(parts[4])
                except ValueError:
                    continue
                if expiry == 0:
                    continue
                if expiry < now:
                    expired += 1
                elif soonest is None or expiry < soonest:
                    soonest = expiry

        if total == 0:
            print("⚠️ cookies 檔案沒有任何有效條目，YouTube 將視為未登入")
            return

        summary = f"🍪 cookies 統計: {total} 筆 / {len(domains)} 網域, 已過期 {expired} 筆"
        if auth_names:
            summary += f", 登入用 cookie: {', '.join(sorted(auth_names))}"
        else:
            summary += ", ⚠️ 缺少登入用 cookie（SID/SAPISID 等）"
        if soonest:
            try:
                summary += f", 最早到期 {time.strftime('%Y-%m-%d', time.gmtime(soonest))}"
            except (ValueError, OSError, OverflowError):
                pass
        print(summary)

        youtube_auth = {
            host: names
            for host, names in auth_by_domain.items()
            if "youtube.com" in host
        }
        if youtube_auth:
            for host, names in sorted(youtube_auth.items()):
                print(f"🍪 {host} 登入 cookie: {', '.join(sorted(names))}")
        else:
            print(
                "⚠️ cookies 中沒有 youtube.com 網域的登入 cookie"
                f"（目前只有 {', '.join(sorted(auth_by_domain)) or '無'}）。"
                " 請從已登入 YouTube 的分頁匯出 youtube.com 的 cookies。"
            )

        if expired and expired == total:
            print("⚠️ 所有 cookies 都已過期，請更新 Secret Manager 的 youtube-cookies")
    except Exception as exc:
        print(f"⚠️ 無法檢查 cookies 狀態: {exc}")


def _supported_clients() -> Tuple[str, ...]:
    """回傳可用的 fallback client 清單（會過濾掉此版本 yt-dlp 不認識的）"""
    configured = os.getenv("YTDLP_YOUTUBE_CLIENTS", "")
    candidates = (
        tuple(c.strip() for c in configured.split(",") if c.strip())
        or _DEFAULT_CLIENT_FALLBACKS
    )

    try:
        from yt_dlp.extractor.youtube._base import INNERTUBE_CLIENTS

        return tuple(c for c in candidates if c in INNERTUBE_CLIENTS)
    except Exception:
        return candidates


def _impersonate_targets() -> List[Optional[str]]:
    """回傳要嘗試的 TLS 指紋偽裝目標

    YouTube 的機器人判斷會看 TLS / HTTP2 指紋，
    用 curl_cffi 假裝成真實瀏覽器有機會避開資料中心 IP 的封鎖。
    第一個 None 代表「先用預設不偽裝」。
    """
    forced = os.getenv("YTDLP_IMPERSONATE", "").strip()
    if forced:
        return [None, forced]

    try:
        import curl_cffi  # noqa: F401
    except Exception:
        return [None]

    return [None, "chrome", "safari"]


def _apply_impersonate(opts: Dict, target: Optional[str]) -> None:
    if not target:
        return
    try:
        from yt_dlp.networking.impersonate import ImpersonateTarget

        opts["impersonate"] = ImpersonateTarget.from_str(target)
    except Exception as exc:
        print(f"⚠️ 無法套用 impersonate={target}: {exc}")


def _build_ydl_opts(
    workdir: str, client: Optional[str], cookiefile: Optional[str]
) -> Dict:
    opts: Dict = {
        # 只要音訊即可，優先取 m4a，取不到就退而求其次
        "format": "bestaudio[ext=m4a]/bestaudio[ext=webm]/bestaudio/best",
        # 用影片 ID 當檔名：標題可能含 emoji 或斜線，容易造成找不到檔案
        "outtmpl": os.path.join(workdir, "%(id)s.%(ext)s"),
        # watch?v=xxx&list=yyy 這類連結不要把整個播放清單抓下來
        "noplaylist": True,
        "quiet": True,
        "no_warnings": False,
        "noprogress": True,
        "retries": 5,
        "fragment_retries": 5,
        "extractor_retries": 3,
        "socket_timeout": 30,
        "overwrites": True,
        # yt-dlp 已將「沒有 JS runtime 的 YouTube 抽取」標記為 deprecated，
        # 沒有 runtime 會缺少格式甚至整個抽取失敗。deno 為預設，另外開啟 node。
        "js_runtimes": {"deno": {}, "node": {}},
    }

    proxy = os.getenv("YTDLP_PROXY")
    if proxy:
        opts["proxy"] = proxy
        print(f"🔌 使用代理: {proxy}")

    if cookiefile:
        opts["cookiefile"] = cookiefile

    browser = os.getenv("YTDLP_COOKIES_FROM_BROWSER")
    if browser and not cookiefile:
        opts["cookiesfrombrowser"] = (browser, None, None, None)

    if client:
        opts["extractor_args"] = {"youtube": {"player_client": [client]}}

    return opts


def _find_downloaded_media(workdir: str) -> Optional[str]:
    """在工作目錄中找出下載好的音檔（取最大的媒體檔）"""
    candidates = []
    for name in os.listdir(workdir):
        path = os.path.join(workdir, name)
        if not os.path.isfile(path):
            continue
        if name.endswith(".part") or name == "cookies.txt":
            continue
        if name.lower().endswith(_MEDIA_EXTENSIONS):
            candidates.append(path)

    if not candidates:
        return None
    return max(candidates, key=os.path.getsize)


def _max_duration_seconds() -> int:
    try:
        return int(os.getenv("YOUTUBE_MAX_DURATION_SECONDS", DEFAULT_MAX_DURATION_SECONDS))
    except ValueError:
        return DEFAULT_MAX_DURATION_SECONDS


def download_youtube_audio_with_ytdlp(
    url: str, workdir: str = "shorts_cache"
) -> Tuple[Optional[str], Dict]:
    """使用 yt-dlp 下載 YouTube 音訊（支援一般影片與 Shorts）

    會依序嘗試預設抽取流程與多個 innertube client，
    以降低在伺服器 IP 上被 YouTube 擋下的機率。

    Returns:
        tuple: (audio_file_path, video_info_dict)
        失敗時回傳 (None, {"error": ...})
    """
    session_dir = None
    try:
        os.makedirs(workdir, exist_ok=True)

        video_id = extract_video_id(url)
        if not video_id:
            raise ValueError(f"無效的YouTube URL: {url}")

        print(f"🎬 正在使用yt-dlp處理YouTube影片: {url}")

        # 每次請求使用獨立目錄，避免與其他請求或殘留檔案互相干擾
        session_dir = tempfile.mkdtemp(prefix=f"yt_{video_id}_", dir=workdir)
        cookiefile = _resolve_cookiefile(session_dir)

        # 嘗試順序：先用預設流程（品質最好），失敗才逐一換 player client；
        # 整輪都被擋下時，再開啟 TLS 指紋偽裝重跑一輪。
        clients: List[Optional[str]] = [None] + list(_supported_clients())
        attempts: List[Tuple[Optional[str], Optional[str]]] = [
            (client, impersonate)
            for impersonate in _impersonate_targets()
            for client in clients
        ]
        failures: List[str] = []

        for attempt, impersonate in attempts:
            label = attempt or "default"
            if impersonate:
                label = f"{label}+{impersonate}"
            try:
                if attempt or impersonate:
                    print(f"🔁 改用「{label}」重試...")

                opts = _build_ydl_opts(session_dir, attempt, cookiefile)
                _apply_impersonate(opts, impersonate)
                with yt_dlp.YoutubeDL(opts) as ydl:
                    print("📋 正在獲取影片資訊...")
                    info = ydl.extract_info(url, download=False)

                    if info.get("_type") == "playlist":
                        entries = [e for e in (info.get("entries") or []) if e]
                        if not entries:
                            raise Exception("連結沒有可下載的影片")
                        info = entries[0]

                    if info.get("is_live"):
                        raise Exception("此連結為進行中的直播，暫不支援")

                    duration = info.get("duration") or 0
                    limit = _max_duration_seconds()
                    if duration and duration > limit:
                        raise Exception(
                            f"影片長度 {duration} 秒超過上限 {limit} 秒"
                        )

                    title = info.get("title", "未知標題")
                    author = info.get("uploader", "未知作者")
                    description = info.get("description", "") or ""
                    view_count = info.get("view_count", 0) or 0

                    print(f"📺 影片標題: {title}")
                    print(f"👤 作者: {author}")
                    print(f"⏱️ 長度: {duration}秒")
                    print(f"👁️ 觀看次數: {view_count}")

                    print("⬇️ 開始下載音頻...")
                    ydl.download([url])

                audio_file_path = _find_downloaded_media(session_dir)
                if not audio_file_path:
                    raise Exception("音頻下載失敗，找不到下載的文件")

                file_size = os.path.getsize(audio_file_path)
                if file_size == 0:
                    raise Exception("音頻下載失敗，檔案為空")

                print(
                    f"✅ 音頻下載完成: {audio_file_path} "
                    f"({file_size / 1024 / 1024:.1f}MB)"
                )

                video_data = {
                    "title": title,
                    "author": author,
                    "description": description,
                    "duration": duration,
                    "view_count": view_count,
                    "video_id": video_id,
                    "_session_dir": session_dir,
                }
                return audio_file_path, video_data

            except Exception as exc:
                failures.append(f"[{label}] {exc}")
                print(f"⚠️ 使用 {label} 失敗: {exc}")
                # 清掉這次嘗試留下的半成品，避免污染下一次嘗試
                for name in os.listdir(session_dir):
                    if name == "cookies.txt":
                        continue
                    try:
                        os.remove(os.path.join(session_dir, name))
                    except OSError:
                        pass

        joined = " | ".join(failures[-4:])
        if "not a bot" in joined or "Sign in to confirm" in joined:
            raise Exception(
                "YouTube 要求登入驗證（伺服器 IP 被判定為機器人）。"
                "請更新 Secret Manager 的 youtube-cookies（現有 cookies 可能已過期），"
                "或設定 YTDLP_PROXY 走住宅 IP。原始錯誤 -> " + joined
            )
        raise Exception("所有下載方式皆失敗 -> " + joined)

    except Exception as exc:
        if session_dir:
            shutil.rmtree(session_dir, ignore_errors=True)
        error_msg = f"yt-dlp YouTube下載失敗: {exc}"
        print(f"❌ {error_msg}")
        return None, {"error": error_msg}


# ---------------------------------------------------------------------------
# 對外主流程
# ---------------------------------------------------------------------------


def process_youtube_video(url: str) -> Dict:
    """
    處理YouTube影片：下載、轉錄、分析（支援一般影片與 Shorts）

    Returns:
        Dict: 包含raw_output和ai_input的結果
    """
    session_dir = None
    try:
        audio_path, video_info = download_youtube_audio_with_ytdlp(url)
        session_dir = video_info.get("_session_dir")

        if audio_path is None:
            error_text = video_info.get("error", "下載失敗")
            return {
                "raw_output": {
                    "description": error_text,
                    "caption": "(影片下載失敗)",
                    "title": "未知標題",
                    "author": "未知作者",
                    "view_count": 0,
                    "duration": 0,
                    "error": error_text,
                },
                "ai_input": {
                    "original_path": url,
                    "ocr_text": "",
                    "caption": "(影片下載失敗)",
                },
            }

        video_title = video_info.get("title", "")
        cleaned_description = clean_description(video_info.get("description", ""))

        # 標題與說明欄的前段拿來當 Whisper 的提示詞，
        # 讓影片中提到的店名、地名有正確的寫法可以對齊
        whisper_context = video_title
        if cleaned_description:
            whisper_context = f"{video_title}\n{cleaned_description[:400]}"

        print("🎙️ 開始語音轉文字...")
        caption = audio_to_text(audio_path, context=whisper_context)

        if not caption:
            caption = "(無法轉錄音頻)"
            print("⚠️ 語音轉文字失敗")

        # ocr_text = 標題 + 清理過的說明欄。
        # 說明欄常常直接列出本集造訪的店家與時間軸章節，
        # 對地點抽取的價值往往高於逐字稿。
        ocr_text = video_title
        if cleaned_description:
            ocr_text = f"{video_title}\n\n【影片說明】\n{cleaned_description}"
            print(f"📝 已納入說明欄內容（{len(cleaned_description)} 字）")

        result = {
            "raw_output": {
                "description": video_info.get("description", ""),
                "caption": caption,
                "title": video_title,
                "author": video_info.get("author", ""),
                "view_count": video_info.get("view_count", 0),
                "duration": video_info.get("duration", 0),
            },
            "ai_input": {
                "original_path": url,
                "ocr_text": ocr_text,  # 影片標題（作者核心文案）
                "caption": caption,  # Whisper 語音轉文字
            },
        }

        print("✅ YouTube影片處理完成")
        return result

    except Exception as exc:
        error_msg = f"處理YouTube影片時發生錯誤: {exc}"
        print(f"❌ {error_msg}")

        return {
            "raw_output": {
                "description": error_msg,
                "caption": "(處理失敗)",
                "title": "未知標題",
                "author": "未知作者",
                "view_count": 0,
                "duration": 0,
                "error": error_msg,
            },
            "ai_input": {"original_path": url, "ocr_text": "", "caption": "(處理失敗)"},
        }
    finally:
        # 清理該次請求的暫存目錄（含下載的音檔）
        if session_dir and os.path.isdir(session_dir):
            shutil.rmtree(session_dir, ignore_errors=True)
            print("🗑️ 已清理暫存檔案")


# 測試函數
if __name__ == "__main__":
    import sys

    test_url = (
        sys.argv[1]
        if len(sys.argv) > 1
        else "https://www.youtube.com/shorts/xNSo6xoFsYc"
    )
    result = process_youtube_video(test_url)
    print("測試結果:", result)
