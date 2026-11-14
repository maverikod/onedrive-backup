"""FastAPI HTML admin browser for versioned OneDrive backup snapshots.

All /ui routes require both TLS client certificate at the mTLS listener and
an independent admin password/session. Other JSON-RPC/REST routes keep their
existing mTLS-only machine-client contract.
"""
from __future__ import annotations

import asyncio
from html import escape
import hmac
import os
from pathlib import Path
import secrets
from typing import Callable
from urllib.parse import parse_qs, quote, urlencode

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse

from .admin_password import (
    AuthError, LOGIN_COOKIE, SESSION_COOKIE, SESSION_SECONDS,
    Throttle, authenticate_session, issue_session, load_record, verify_password,
)
from .catalog import Catalog, CatalogError


_STYLES = """
:root{color-scheme:dark;font:16px system-ui,sans-serif}
*{box-sizing:border-box}
body{background:#0d1422;color:#e3eaf5;margin:0}
main{max-width:1160px;margin:38px auto;padding:0 20px 50px}
header{background:#142136;padding:18px 26px;border-bottom:1px solid #293b58}
header a{color:#c1e3ff;text-decoration:none}
h1{font-size:1.75rem;margin:0 0 8px}
h2{font-size:1.16rem;margin:18px 0}
p{line-height:1.6}
.muted{color:#9eafc8}
.panel{background:#18253b;border:1px solid #2d4260;border-radius:12px;padding:24px;margin:18px 0}
table{width:100%;border-collapse:collapse;margin-top:12px}
th,td{text-align:left;padding:12px 10px;border-bottom:1px solid #34445b;vertical-align:middle}
th{color:#b9c9df;font-weight:600}
a{color:#89d0ff}
.button,button{display:inline-block;font:inherit;padding:9px 15px;background:#246bb0;
 color:white;border:0;border-radius:7px;cursor:pointer;text-decoration:none}
button:hover,.button:hover{background:#3286d1}
input{font:inherit;background:#0d1829;color:#fff;border:1px solid #50708d;
 padding:10px 12px;border-radius:7px;max-width:100%;margin:8px 0}
input[type=password]{display:block;width:100%;max-width:420px}
form.inline{display:inline-block;margin:0 4px}
code{overflow-wrap:anywhere;color:#d3deee}
.error{padding:12px 16px;color:#ffd1d1;background:#5f2335;border-radius:8px}
.toolbar{display:flex;justify-content:space-between;align-items:center;gap:15px;flex-wrap:wrap}
.small{font-size:.85rem}
.pagination{display:flex;gap:15px;margin-top:18px}
"""

def _h(value: object) -> str:
    return escape(str(value), quote=True)


def _layout(title: str, content: str, *, authenticated: bool = False, csrf: str = "") -> HTMLResponse:
    logout = ""
    if authenticated:
        logout = ('<form class="inline" method="post" action="/ui/logout">'
                  '<input type="hidden" name="csrf" value="' + _h(csrf) + '">'
                  '<button type="submit">Выйти (admin)</button></form>')
    markup = (
        '<!doctype html><html lang="ru"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        '<title>' + _h(title) + ' — OneDrive Backup</title>'
        '<style>' + _STYLES + '</style></head><body>'
        '<header><div class="toolbar"><strong>OneDrive Backup · Администрирование</strong>'
        '<div><a href="/ui/">Снимки</a> &nbsp; ' + logout + '</div></div></header>'
        '<main><h1>' + _h(title) + '</h1>' + content + '</main></body></html>'
    )
    return HTMLResponse(markup)


async def _form(request: Request) -> dict[str, str]:
    if request.headers.get("content-type", "").split(";")[0].strip() != "application/x-www-form-urlencoded":
        raise HTTPException(415, "Требуется форма application/x-www-form-urlencoded")
    raw = await request.body()
    if len(raw) > 8192:
        raise HTTPException(413, "Слишком большая форма")
    try:
        pairs = parse_qs(raw.decode("utf-8"), keep_blank_values=True, max_num_fields=12)
        if any(len(v) != 1 for v in pairs.values()):
            raise ValueError("Duplicate form keys")
        return {key: values[0] for key, values in pairs.items()}
    except (ValueError, UnicodeDecodeError) as exc:
        raise HTTPException(400, "Некорректная форма") from exc


def install_ui(app: FastAPI, catalog_factory: Callable[[], Catalog],
               password_file: Path | str | None = None) -> None:
    """Attach browser routes to the existing adapter FastAPI application."""
    credential_path = Path(password_file or
                           os.environ.get("ONEDRIVE_ADMIN_HASH_FILE",
                                          "/config/admin-password.hash"))
    throttle = Throttle()

    @app.middleware("http")
    async def ui_security_headers(request: Request, call_next):
        response = await call_next(request)
        if request.url.path.startswith("/ui"):
            response.headers["Cache-Control"] = "no-store, private"
            response.headers["X-Content-Type-Options"] = "nosniff"
            response.headers["X-Frame-Options"] = "DENY"
            response.headers["Referrer-Policy"] = "no-referrer"
            response.headers["Strict-Transport-Security"] = "max-age=31536000"
            response.headers["Content-Security-Policy"] = (
                "default-src 'none'; style-src 'unsafe-inline'; "
                "form-action 'self'; base-uri 'none'; frame-ancestors 'none'"
            )
        return response

    def record() -> str:
        try:
            return load_record(credential_path)
        except AuthError as exc:
            raise HTTPException(503, "Пароль admin не настроен. "
                                    "Задайте его командой onedrive-backup-admin-password.") from exc

    def current(request: Request) -> dict | None:
        return authenticate_session(record(), request.cookies.get(SESSION_COOKIE))

    def required(request: Request) -> dict:
        user = current(request)
        if user is None:
            raise HTTPException(303, headers={"Location": "/ui/login"})
        return user

    def check_csrf(state: dict, value: str | None) -> None:
        if not value or not hmac.compare_digest(value, state["csrf"]):
            raise HTTPException(403, "Неверный CSRF-токен")

    @app.get("/ui", include_in_schema=False)
    async def redirect_ui():
        return RedirectResponse("/ui/", status_code=307)

    @app.get("/ui/login", include_in_schema=False)
    async def login_form(request: Request):
        if current(request):
            return RedirectResponse("/ui/", status_code=303)
        nonce = secrets.token_urlsafe(24)
        body = (
            '<div class="panel"><p>Доступ к архивам защищён сертификатом mTLS '
            'и дополнительным паролем администратора.</p>'
            '<form action="/ui/login" method="post">'
            '<label>Имя пользователя<input name="username" value="admin" autocomplete="username" required></label><br>'
            '<label>Пароль<input type="password" name="password" autocomplete="current-password" required></label>'
            '<input type="hidden" name="csrf" value="' + _h(nonce) + '">'
            '<button type="submit">Войти</button></form></div>'
        )
        response = _layout("Вход", body)
        response.set_cookie(LOGIN_COOKIE, nonce, secure=True, httponly=True,
                            samesite="strict", path="/ui", max_age=600)
        return response

    @app.post("/ui/login", include_in_schema=False)
    async def login(request: Request):
        data = await _form(request)
        record_value = record()
        peer = request.client.host if request.client else "unknown"
        if not throttle.allowed(peer):
            raise HTTPException(429, "Слишком много попыток. Повторите позднее.")
        supplied = data.get("csrf", "")
        expected = request.cookies.get(LOGIN_COOKIE, "")
        if not expected or not hmac.compare_digest(supplied, expected):
            raise HTTPException(403, "Неверный CSRF-токен входа")
        username_ok = hmac.compare_digest(data.get("username", "").encode("utf-8"), b"admin")
        password_ok = await asyncio.to_thread(verify_password, data.get("password", ""),
                                              record_value)
        if not (username_ok and password_ok):
            throttle.failed(peer)
            return _layout("Вход", '<p class="error">Неверное имя или пароль.</p>'
                           '<p><a href="/ui/login">Повторить вход</a></p>')
        throttle.succeeded(peer)
        cookie, _ = issue_session(record_value)
        response = RedirectResponse("/ui/", status_code=303)
        response.set_cookie(SESSION_COOKIE, cookie, secure=True, httponly=True,
                            samesite="strict", path="/ui", max_age=SESSION_SECONDS)
        response.delete_cookie(LOGIN_COOKIE, path="/ui", secure=True, httponly=True,
                               samesite="strict")
        return response

    @app.post("/ui/logout", include_in_schema=False)
    async def logout(request: Request):
        state = required(request)
        data = await _form(request)
        check_csrf(state, data.get("csrf"))
        response = RedirectResponse("/ui/login", status_code=303)
        response.delete_cookie(SESSION_COOKIE, path="/ui", secure=True, httponly=True,
                               samesite="strict")
        return response

    @app.get("/ui/", include_in_schema=False)
    async def snapshots(request: Request):
        state = required(request)
        try:
            data = await asyncio.to_thread(catalog_factory().snapshots, 100)
            rows = []
            for snapshot in data["items"]:
                sid = str(snapshot.get("id", ""))
                url = "/ui/snapshots/" + quote(sid, safe="")
                rows.append(
                    "<tr><td><a href='" + _h(url) + "'><code>" +
                    _h(sid[:20]) + "</code></a></td><td>" +
                    _h(snapshot.get("time", "")) + "</td><td>" +
                    _h(", ".join(map(str, snapshot.get("tags", [])))) + "</td><td>" +
                    '<a class="button" href="' + _h(url) + '">Открыть</a></td></tr>'
                )
            table = ('<table><thead><tr><th>Снимок</th><th>Дата</th><th>Теги</th>'
                     '<th></th></tr></thead><tbody>' + "".join(rows) + '</tbody></table>')
            return _layout("Снимки резервных копий",
                           '<p class="muted">Всего снимков: ' + str(data["count"]) + '</p>' +
                           ('<div class="panel">' + table + '</div>' if rows else
                            '<div class="panel">Снимков пока нет.</div>'),
                           authenticated=True, csrf=state["csrf"])
        except CatalogError as exc:
            return _layout("Снимки резервных копий",
                           '<p class="error">' + _h(exc) + '</p>',
                           authenticated=True, csrf=state["csrf"])

    @app.get("/ui/snapshots/{snapshot_id}", include_in_schema=False)
    async def snapshot_files(request: Request, snapshot_id: str, prefix: str = "",
                             offset: int = 0):
        state = required(request)
        try:
            data = await asyncio.to_thread(catalog_factory().files,
                                           snapshot_id, prefix, 100, offset)
            sid = quote(snapshot_id, safe="")
            rows = []
            for node in data["items"]:
                rel = str(node.get("path", ""))
                is_dir = node.get("type") == "dir"
                if is_dir:
                    url = "/ui/snapshots/" + sid + "?" + urlencode({"prefix": rel})
                    controls = '<a href="' + _h(url) + '">Открыть каталог</a>'
                elif node.get("type") == "file":
                    controls = ('<form class="inline" method="post" action="/ui/export">'
                                '<input type="hidden" name="csrf" value="' + _h(state["csrf"]) + '">'
                                '<input type="hidden" name="snapshot_id" value="' + _h(snapshot_id) + '">'
                                '<input type="hidden" name="file_path" value="' + _h(rel) + '">'
                                '<button type="submit">Скачать</button></form>')
                else:
                    controls = ""
                rows.append('<tr><td><code>' + _h(rel) + '</code></td><td>' +
                            _h(node.get("type", "")) + '</td><td>' +
                            _h(node.get("size", "")) + '</td><td>' + controls + '</td></tr>')
            form = ('<form method="post" action="/ui/export">'
                    '<input type="hidden" name="csrf" value="' + _h(state["csrf"]) + '">'
                    '<input type="hidden" name="snapshot_id" value="' + _h(snapshot_id) + '">'
                    '<button type="submit">Подготовить полный снимок (.tar.gz)</button></form>')
            pagination = ""
            for label, value in (("← Назад", offset - 100),
                                 ("Вперёд →", offset + 100)):
                if 0 <= value < data["total"]:
                    url = "/ui/snapshots/" + sid + "?" + urlencode(
                        {"prefix": prefix, "offset": value})
                    pagination += '<a href="' + _h(url) + '">' + label + '</a> &nbsp; '
            content = ('<p><a href="/ui/">← Ко всем снимкам</a></p><p>Снимок: <code>' +
                       _h(snapshot_id) + '</code></p>'
                       '<div class="panel">' + form + '</div>'
                       '<p class="muted">Файлов и каталогов по фильтру: ' +
                       str(data["total"]) + ' · страница с ' + str(offset) + '</p>'
                       '<div class="panel"><table><thead><tr><th>Путь</th><th>Тип</th>'
                       '<th>Размер</th><th>Действия</th></tr></thead><tbody>' +
                       "".join(rows) + '</tbody></table><p class="pagination">' +
                       pagination + '</p></div>')
            return _layout("Содержимое резервной копии", content,
                           authenticated=True, csrf=state["csrf"])
        except CatalogError as exc:
            return _layout("Ошибка просмотра", '<p class="error">' + _h(exc) + '</p>',
                           authenticated=True, csrf=state["csrf"])

    @app.post("/ui/export", include_in_schema=False)
    async def export(request: Request):
        state = required(request)
        form = await _form(request)
        check_csrf(state, form.get("csrf"))
        snap = form.get("snapshot_id", "")
        file_path = form.get("file_path") or None
        try:
            meta = await asyncio.to_thread(catalog_factory().prepare, snap, file_path)
        except CatalogError as exc:
            raise HTTPException(exc.status, detail=str(exc)) from exc
        return RedirectResponse("/ui/exports/" + quote(meta["export_id"], safe=""),
                                status_code=303)

    @app.get("/ui/exports/{export_id}", include_in_schema=False)
    async def export_ready(request: Request, export_id: str):
        state = required(request)
        try:
            meta = await asyncio.to_thread(catalog_factory().export_status, export_id)
        except CatalogError as exc:
            raise HTTPException(exc.status, detail=str(exc)) from exc
        url = "/ui/exports/" + quote(export_id, safe="") + "/download"
        content = ('<div class="panel"><p>Файл: <code>' + _h(meta["filename"]) +
                   '</code></p><p>Размер: ' + str(meta["size_bytes"]) +
                   ' байт</p><p>SHA-256: <code>' + _h(meta["sha256"]) + '</code></p>'
                   '<p><a class="button" href="' + _h(url) + '">Скачать файл</a></p>'
                   '<p class="muted">Выгрузка временная, срок действия: ' +
                   _h(meta["expires_at"]) + '</p>'
                   '<form method="post" action="/ui/exports/' + _h(export_id) +
                   '/delete"><input type="hidden" name="csrf" value="' +
                   _h(state["csrf"]) + '"><button type="submit">Удалить выгрузку</button>'
                   '</form></div>')
        return _layout("Выгрузка готова", content, authenticated=True, csrf=state["csrf"])

    @app.get("/ui/exports/{export_id}/download", include_in_schema=False)
    async def export_download(request: Request, export_id: str):
        required(request)
        try:
            meta, filename = await asyncio.to_thread(catalog_factory().get_export, export_id)
        except CatalogError as exc:
            raise HTTPException(exc.status, detail=str(exc)) from exc
        return FileResponse(filename, media_type="application/octet-stream",
                            filename=meta["filename"],
                            headers={"X-Content-SHA256": meta["sha256"],
                                     "Cache-Control": "no-store"})

    @app.post("/ui/exports/{export_id}/delete", include_in_schema=False)
    async def delete_export(request: Request, export_id: str):
        state = required(request)
        form = await _form(request)
        check_csrf(state, form.get("csrf"))
        try:
            await asyncio.to_thread(catalog_factory().delete_export, export_id)
        except CatalogError as exc:
            raise HTTPException(exc.status, detail=str(exc)) from exc
        return RedirectResponse("/ui/", status_code=303)

