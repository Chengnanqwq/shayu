# -*- coding: utf-8 -*-
"""自己实现的 QQ 空间发帖 / 删帖（不依赖 qzone daemon）。

依赖：SnowLuma 的 HTTP 接口 http://127.0.0.1:3000/get_cookies 拿登录 cookie。
用法：
    from qzone_self import publish, delete_post, qzone_uin
    print(publish("测试说说"))
"""
from __future__ import annotations

import json
import re
import time

import requests

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/120.0 Safari/537.36")
COOKIE_API = "http://127.0.0.1:3000/get_cookies"
PUBLISH_URL = ("https://user.qzone.qq.com/proxy/domain/taotao.qzone.qq.com"
               "/cgi-bin/emotion_cgi_publish_v6")
DELETE_URL = ("https://user.qzone.qq.com/proxy/domain/taotao.qzone.qq.com"
              "/cgi-bin/emotion_cgi_delete_v6")
# QZONE_1105：读说说 / 点赞 / 评论
LIST_URL = ("https://user.qzone.qq.com/proxy/domain/taotao.qq.com"
            "/cgi-bin/emotion_cgi_msglist_v6")
LIKE_URL = ("https://user.qzone.qq.com/proxy/domain/w.qzone.qq.com"
            "/cgi-bin/likes/internal_dolike_app")
COMMENT_URL = ("https://user.qzone.qq.com/proxy/domain/taotao.qzone.qq.com"
               "/cgi-bin/emotion_cgi_re_feeds")
UPLOAD_IMAGE_URL = "https://up.qzone.qq.com/cgi-bin/upload/cgi_upload_image"
VISITOR_URL = ("https://h5.qzone.qq.com/proxy/domain/g.qzone.qq.com"
               "/cgi-bin/friendshow/cgi_get_visitor_more")
REPLY_URL = ("https://h5.qzone.qq.com/proxy/domain/taotao.qzone.qq.com"
             "/cgi-bin/emotion_cgi_re_feeds")


def get_cookies(domain: str = "user.qzone.qq.com") -> str:
    """从 OneBot 客户端拿 qzone cookie，返回 'a=1; b=2' 形式的字符串。"""
    r = requests.post(COOKIE_API, json={"domain": domain}, timeout=10)
    data = r.json()
    cookies = (data.get("data") or {}).get("cookies") or ""
    if not cookies:
        raise RuntimeError("拿不到 cookie（SnowLuma 可能没登录）")
    return cookies


def parse_cookie(cookie_text: str) -> dict:
    out = {}
    for item in cookie_text.split(";"):
        if "=" in item:
            k, v = item.split("=", 1)
            out[k.strip()] = v.strip()
    return out


def qzone_uin(cookie_text: str) -> str:
    jar = parse_cookie(cookie_text)
    uin = jar.get("p_uin") or jar.get("uin") or jar.get("pt2gguin") or ""
    uin = re.sub(r"\D", "", uin)
    if not uin:
        raise RuntimeError("cookie 里没有 uin")
    return uin


def g_tk(cookie_text: str) -> str:
    """Qzone 的 g_tk 算法：对 skey/p_skey 做 DJB hash 再 & 0x7fffffff。"""
    jar = parse_cookie(cookie_text)
    skey = jar.get("p_skey") or jar.get("skey") or ""
    if not skey:
        raise RuntimeError("cookie 里没有 skey/p_skey")
    h = 5381
    for ch in skey:
        h += (h << 5) + ord(ch)
    return str(h & 0x7FFFFFFF)


def _headers(cookie_text: str, uin: str) -> dict:
    return {
        "Cookie": cookie_text,
        "User-Agent": UA,
        "Referer": f"https://user.qzone.qq.com/{uin}",
        "Origin": "https://user.qzone.qq.com",
    }


def publish(content: str) -> str:
    """发一条纯文字说说，成功返回 'ok:<tid>'，失败抛 RuntimeError。"""
    cookie_text = get_cookies()
    uin = qzone_uin(cookie_text)
    tk = g_tk(cookie_text)
    payload = {
        "syn_tweet_verson": "1",
        "paramstr": "1",
        "who": "1",
        "con": content,
        "feedversion": "1",
        "ver": "1",
        "ugc_right": "1",
        "to_sign": "0",
        "hostuin": uin,
        "code_version": "1",
        "format": "json",
        "qzreferrer": f"https://user.qzone.qq.com/{uin}",
    }
    r = requests.post(PUBLISH_URL, params={"g_tk": tk}, data=payload,
                      headers=_headers(cookie_text, uin), timeout=30)
    try:
        data = r.json()
    except Exception:
        raise RuntimeError(f"发布返回非 JSON（{r.status_code}）：{r.text[:120]}")
    if data.get("code") not in (0, None) or data.get("subcode") not in (0, None):
        raise RuntimeError(f"发布失败：code={data.get('code')} msg={data.get('message') or data.get('msg')}")
    body = data.get("data") or {}
    tid = body.get("tid") or body.get("feedid") or ""
    return f"ok:{tid}"


def delete_post(tid: str) -> bool:
    """删一条自己发的说说。tid 形如 'ec02c596...'。"""
    cookie_text = get_cookies()
    uin = qzone_uin(cookie_text)
    tk = g_tk(cookie_text)
    r = requests.post(DELETE_URL, params={"g_tk": tk},
                      data={"tid": tid, "hostuin": uin, "format": "json"},
                      headers=_headers(cookie_text, uin), timeout=30)
    try:
        data = r.json()
    except Exception:
        return False
    return data.get("code") in (0, None)


def _jsonp(text: str):
    """空间很多接口返回 JSONP（_preloadCallback({...})），剥掉外壳再解析。"""
    t = (text or "").strip()
    m = re.match(r"^[\w$.]*\((.*)\)\s*;?\s*$", t, re.S)
    if m:
        t = m.group(1)
    return json.loads(t)


def list_feeds(target_uin: str | None = None, num: int = 5, pos: int = 0) -> list[dict]:
    """读某个 QQ 的说说列表（默认自己）。返回 [{tid, content, time, uin, comments, likes}]。"""
    cookie_text = get_cookies()
    me = qzone_uin(cookie_text)
    tk = g_tk(cookie_text)
    tgt = str(target_uin or me)
    params = {
        "g_tk": tk, "uin": tgt, "ftype": 0, "sort": 0, "pos": pos, "num": max(1, min(num, 20)),
        "replynum": 100, "callback": "_preloadCallback", "code_version": 1,
        "format": "json", "need_comment": 1,
    }
    r = requests.get(LIST_URL, params=params, headers=_headers(cookie_text, me), timeout=30)
    try:
        data = _jsonp(r.text)
    except Exception:
        raise RuntimeError(f"读说说失败（{r.status_code}）：{r.text[:120]}")
    if data.get("code") not in (0, None):
        raise RuntimeError(f"读说说失败：code={data.get('code')} msg={data.get('message') or data.get('msg')}")
    rows = []
    for m in (data.get("msglist") or []):
        # QZONE_1105b：msglist 不返回点赞数（只有 commentlist/cmtnum），
        # 点赞照样能成（接口返回 succ），但列表上没法显示赞数，这里置 -1 表示未知
        _cl = m.get("commentlist") or []
        _detail = []
        for _c in _cl[:10]:
            _detail.append({
                "tid": str(_c.get("tid") or ""),
                "uin": str(_c.get("uin") or ""),
                "name": str(_c.get("name") or ""),
                "content": re.sub(r"\s+", " ", str(_c.get("content") or ""))[:60],
            })
        rows.append({
            "tid": str(m.get("tid") or ""),
            "content": re.sub(r"\s+", " ", str(m.get("content") or "")).strip(),
            "time": m.get("created_time") or "",
            "uin": str(m.get("uin") or tgt),
            "comments": int(m.get("cmtnum") or len(_cl)),
            "likes": -1,
            "comments_detail": _detail,
        })
    return rows


def like_post(tid: str, target_uin: str) -> bool:
    """给某条说说点赞。"""
    cookie_text = get_cookies()
    me = qzone_uin(cookie_text)
    tk = g_tk(cookie_text)
    curkey = f"http://user.qzone.qq.com/{target_uin}/mood/{tid}"
    data = {
        "qzreferrer": f"https://user.qzone.qq.com/{me}", "opuin": me,
        "unikey": curkey, "curkey": curkey, "appid": 311, "from": 1, "typeid": 0,
        "abstime": int(time.time()), "fid": tid, "active": 0,
        "format": "json", "fupdate": 1,
    }
    r = requests.post(LIKE_URL, params={"g_tk": tk}, data=data,
                      headers=_headers(cookie_text, me), timeout=30)
    try:
        j = r.json()
    except Exception:
        j = {}
    return (j.get("code") in (0, None)) and (j.get("subcode") in (0, None))


def comment_post(tid: str, target_uin: str, content: str) -> tuple[bool, str]:
    """评论某条说说。返回 (成功, 说明)。"""
    content = (content or "").strip()[:150]
    if not content:
        return False, "评论内容空了"
    cookie_text = get_cookies()
    me = qzone_uin(cookie_text)
    tk = g_tk(cookie_text)
    data = {
        "topicId": f"{target_uin}_{tid}__1", "uin": me, "hostUin": target_uin,
        "feedsType": 100, "inCharset": "utf-8", "outCharset": "utf-8",
        "plat": "qzone", "source": "ic", "platformid": 52,
        # QZONE_1105c：必须用 json。上游插件写的是 "fs"，那是 frame-script 格式，
        # 返回一整段 HTML（回调都包在 <script> 里），解析必然失败。
        "format": "json", "ref": "feeds", "content": content,
    }
    r = requests.post(COMMENT_URL, params={"g_tk": tk}, data=data,
                      headers=_headers(cookie_text, me), timeout=30)
    txt = (r.text or "").strip()
    if not txt:
        return False, f"空响应（{r.status_code}）"
    # 正常的返回是 JSON/JSONP，异常时会是一段 HTML 提示（比如没有权限）
    try:
        j = _jsonp(txt) if txt[0] in "_{([abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ" else json.loads(txt)
    except Exception:
        if "验证" in txt or "登录" in txt:
            return False, "被要求验证/登录，cookie 可能失效"
        return False, f"返回不是 JSON（{r.status_code}）"
    code = j.get("code")
    sub = j.get("subcode")
    if code in (0, None) and sub in (0, None):
        return True, str(j.get("message") or "ok")
    return False, f"code={code} subcode={sub} msg={j.get('message') or j.get('msg')}"


def upload_image(image_bytes: bytes) -> tuple[str, str]:
    """传一张图到相册，返回 (picbo, richval)，发带图说说时要用。"""
    cookie_text = get_cookies()
    me = qzone_uin(cookie_text)
    jar = parse_cookie(cookie_text)
    skey = jar.get("p_skey") or jar.get("skey") or ""
    import base64 as _b64
    data = {
        "filename": "filename", "uploadtype": "1", "albumtype": "7",
        "skey": skey, "uin": me, "p_skey": skey,
        "output_type": "json", "base64": "1",
        "picfile": _b64.b64encode(image_bytes).decode(),
    }
    headers = {"Cookie": cookie_text, "User-Agent": UA,
               "referer": f"https://user.qzone.qq.com/{me}",
               "origin": "https://user.qzone.qq.com"}
    r = requests.post(UPLOAD_IMAGE_URL, data=data, headers=headers, timeout=60)
    # QZONE_1105e：这个接口回的是 JSONP（_Callback({...})），不是裸 JSON
    try:
        j = _jsonp(r.text)
    except Exception:
        raise RuntimeError(f"传图返回无法解析（{r.status_code}）：{r.text[:120]}")
    if j.get("ret") not in (0, "0", None):
        raise RuntimeError(f"传图失败：ret={j.get('ret')} msg={j.get('msg')}")
    d = j.get("data") or {}
    url = str(d.get("url") or d.get("pre") or "")
    if not url:
        raise RuntimeError(f"传图没拿到 url：{str(j)[:160]}")
    picbo = url.split("&bo=", 1)[1] if "&bo=" in url else ""
    richval = ",{},{},{},{},{},{},,{},{}".format(
        d.get("albumid", ""), d.get("lloc", ""), d.get("sloc", ""), d.get("type", ""),
        d.get("height", 0), d.get("width", 0), d.get("height", 0), d.get("width", 0))
    return picbo, richval


def publish_with_images(content: str, images: list[bytes]) -> str:
    """发一条带图的说说。images 是图片字节列表。"""
    pic_bos, richvals = [], []
    for img in images[:9]:
        picbo, richval = upload_image(img)
        if picbo:
            pic_bos.append(picbo)
            richvals.append(richval)
    cookie_text = get_cookies()
    uin = qzone_uin(cookie_text)
    tk = g_tk(cookie_text)
    payload = {
        "syn_tweet_verson": "1", "paramstr": "1", "who": "1",
        "con": content, "feedversion": "1", "ver": "1",
        "ugc_right": "1", "to_sign": "0", "hostuin": uin,
        "code_version": "1", "format": "json",
        "qzreferrer": f"https://user.qzone.qq.com/{uin}",
    }
    if pic_bos:
        payload["pic_bo"] = ",".join(pic_bos)
        payload["richtype"] = "1"
        payload["richval"] = "\t".join(richvals)
    r = requests.post(PUBLISH_URL, params={"g_tk": tk}, data=payload,
                      headers=_headers(cookie_text, uin), timeout=60)
    try:
        data = json.loads(r.text)
    except Exception:
        raise RuntimeError(f"发布返回非 JSON（{r.status_code}）：{r.text[:120]}")
    if data.get("code") not in (0, None):
        raise RuntimeError(f"发布失败：code={data.get('code')} msg={data.get('message') or data.get('msg')}")
    body = data.get("data") or {}
    tid = str(body.get("tid") or body.get("feedid") or "")
    if not tid:
        # QZONE_1105f：带图发布时接口不返回 tid，回读一次列表把最新那条的 tid 捞出来
        # （不然发完删不掉，测试说说会一直挂在自己空间上）
        try:
            rows = list_feeds(None, num=1)
            if rows:
                tid = rows[0].get("tid") or ""
        except Exception:
            pass
    return f"ok:{tid} 图 {len(pic_bos)} 张"


def recent_visitors(page: int = 1) -> list[dict]:
    """最近访客。返回 [{uin, name, time}]。"""
    cookie_text = get_cookies()
    me = qzone_uin(cookie_text)
    tk = g_tk(cookie_text)
    params = {"uin": me, "mask": 7, "g_tk": tk, "page": page, "fupdate": 1, "clear": 1}
    r = requests.get(VISITOR_URL, params=params, headers=_headers(cookie_text, me), timeout=30)
    try:
        j = _jsonp(r.text)
    except Exception:
        raise RuntimeError(f"访客接口返回非 JSON（{r.status_code}）：{r.text[:120]}")
    if j.get("code") not in (0, None):
        raise RuntimeError(f"访客接口失败：code={j.get('code')} msg={j.get('message') or j.get('msg')}")
    items = ((j.get("data") or {}).get("items") or [])
    out = []
    for it in items:
        out.append({
            "uin": str(it.get("uin") or ""),
            "name": str(it.get("name") or it.get("nickname") or ""),
            "time": it.get("time") or it.get("lastvtime") or "",
            "src": it.get("src_name") or "",
        })
    return out


def reply_comment(tid: str, target_uin: str, comment_id: str, comment_uin: str,
                  content: str) -> tuple[bool, str]:
    """回复某条评论。comment_id 是被回复评论的 tid，comment_uin 是那个人。"""
    content = (content or "").strip()[:150]
    if not content:
        return False, "内容空了"
    cookie_text = get_cookies()
    me = qzone_uin(cookie_text)
    tk = g_tk(cookie_text)
    data = {
        "topicId": f"{target_uin}_{tid}__1", "uin": me, "hostUin": target_uin,
        "feedsType": 100, "inCharset": "utf-8", "outCharset": "utf-8",
        "plat": "qzone", "source": "ic", "platformid": 50,
        "format": "json", "ref": "feeds", "content": content,
        "commentId": comment_id, "commentUin": comment_uin,
        "t1_uin": target_uin, "t1_tid": tid,
        "t2_uin": comment_uin, "t2_tid": comment_id,
    }
    r = requests.post(REPLY_URL, params={"g_tk": tk}, data=data,
                      headers=_headers(cookie_text, me), timeout=30)
    txt = (r.text or "").strip()
    try:
        j = json.loads(txt)
    except Exception:
        if "验证" in txt or "登录" in txt:
            return False, "被要求验证/登录"
        return False, f"返回不是 JSON（{r.status_code}）：{txt[:80]}"
    if j.get("code") in (0, None) and j.get("subcode") in (0, None):
        return True, "ok"
    return False, f"code={j.get('code')} subcode={j.get('subcode')} msg={j.get('message') or j.get('msg')}"


if __name__ == "__main__":
    import sys

    if len(sys.argv) > 1 and sys.argv[1] == "delete" and len(sys.argv) > 2:
        print("deleted" if delete_post(sys.argv[2]) else "delete failed")
    else:
        text = sys.argv[1] if len(sys.argv) > 1 else f"测试说说 {int(time.time())}"
        print(publish(text))
