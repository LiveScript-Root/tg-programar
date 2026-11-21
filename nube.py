#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Envia a Telegram lo que ya vencio. Corre en GitHub Actions, sin base de datos."""
import csv, html, json, os, random, sys, time, urllib.error, urllib.request
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

BASE = Path(__file__).resolve().parent
CAL = BASE / "calendario.csv"
CANALES = BASE / "canales.txt"
MEDIA = BASE / "contenido"
ESTADO = BASE / "estado.json"
HND = ZoneInfo("America/Tegucigalpa")
API = "https://api.telegram.org/bot{}/{}"
EXTS = [".jpg", ".jpeg", ".png", ".webp", ".mp4", ".mov", ".m4v", ".mkv"]
TOPE_FOTO = 9
TOPE_VIDEO = 48

TOKEN = os.environ.get("BOT_TOKEN", "").strip()
SEGUNDOS = float(os.environ.get("SEGUNDOS", "1.5"))
MAX_ENVIOS = int(os.environ.get("MAX_ENVIOS", "200"))
SIMULAR = "--simular" in sys.argv
IGNORAR_HORA = "--ignorar-hora" in sys.argv


def log(msg):
    print(f"{datetime.now(timezone.utc):%Y-%m-%d %H:%M:%S}Z  {msg}")


def cargar_estado():
    if ESTADO.exists():
        try:
            return json.loads(ESTADO.read_text(encoding="utf-8"))
        except Exception:
            return {}
    return {}


def guardar_estado(e):
    ESTADO.write_text(json.dumps(e, ensure_ascii=False, indent=0), encoding="utf-8")


def canales():
    return [c.strip() for c in CANALES.read_text(encoding="utf-8-sig").splitlines()
            if c.strip() and not c.startswith("#")]


def buscar(archivo):
    for ext in EXTS:
        p = MEDIA / (archivo + ext)
        if p.exists():
            return p
    return None


def items():
    salida = []
    with CAL.open(encoding="utf-8-sig", newline="") as f:
        for r in csv.DictReader(f):
            if not (r.get("fecha") or "").strip():
                continue
            enlace = (r.get("enlace") or "").strip()
            texto = (r.get("texto") or "").replace("{URL}", enlace).strip()
            naive = datetime.strptime(f"{r['fecha'].strip()} {r['hora'].strip()}", "%Y-%m-%d %H:%M")
            salida.append(dict(utc=naive.replace(tzinfo=HND).astimezone(timezone.utc),
                               tipo=r["tipo"].strip().lower(), archivo=r["archivo"].strip(),
                               texto=texto))
    return salida


def api(metodo, campos, archivo=None, campo=None):
    b = "----venice" + str(random.randint(10**12, 10**13))
    partes = []
    for k, v in campos.items():
        partes.append(f"--{b}\r\nContent-Disposition: form-data; name=\"{k}\"\r\n\r\n{v}\r\n".encode())
    if archivo:
        partes.append(
            f"--{b}\r\nContent-Disposition: form-data; name=\"{campo}\"; filename=\"{Path(archivo).name}\"\r\n"
            f"Content-Type: application/octet-stream\r\n\r\n".encode()
            + Path(archivo).read_bytes() + b"\r\n")
    partes.append(f"--{b}--\r\n".encode())
    req = urllib.request.Request(API.format(TOKEN, metodo), data=b"".join(partes),
                                 headers={"Content-Type": f"multipart/form-data; boundary={b}"})
    try:
        with urllib.request.urlopen(req, timeout=300) as r:
            return True, json.loads(r.read().decode()), None
    except urllib.error.HTTPError as e:
        try:
            d = json.loads(e.read().decode())
        except Exception:
            d = {"description": str(e)}
        return False, d, d.get("parameters", {}).get("retry_after")
    except Exception as e:
        return False, {"description": str(e)}, None


def enviar(canal, tipo, ruta, texto):
    campos = {"chat_id": canal, "caption": html.escape(texto, quote=False), "parse_mode": "HTML"}
    mb = ruta.stat().st_size / 1048576
    if tipo == "foto" and mb <= TOPE_FOTO:
        return api("sendPhoto", campos, ruta, "photo")
    if tipo == "video" and mb <= TOPE_VIDEO:
        return api("sendVideo", campos, ruta, "video")
    return api("sendDocument", campos, ruta, "document")


def main():
    if not TOKEN:
        sys.exit("Falta BOT_TOKEN en el entorno")
    estado = cargar_estado()
    guardar_estado(estado)
    ahora = datetime.now(timezone.utc)
    lista, enviados, fallos = items(), 0, 0

    for canal in canales():
        for it in lista:
            clave = f"{canal}|{it['utc'].isoformat()}|{it['archivo']}"
            if clave in estado:
                continue
            if not IGNORAR_HORA and it["utc"] > ahora:
                continue
            ruta = buscar(it["archivo"])
            if not ruta:
                log(f"FALTA  {it['archivo']}  ({canal})")
                continue
            hora_hn = it["utc"].astimezone(HND).strftime("%d/%m %H:%M")
            if SIMULAR:
                log(f"SIMUL  {canal}  {hora_hn} HN  {it['tipo']}  {ruta.name}")
                enviados += 1
                continue
            ok, resp, espera = enviar(canal, it["tipo"], ruta, it["texto"])
            if ok:
                estado[clave] = ahora.isoformat()
                guardar_estado(estado)
                enviados += 1
                log(f"OK     {canal}  {hora_hn} HN  {ruta.name}")
            else:
                fallos += 1
                log(f"FALLO  {canal}  {ruta.name}  {resp.get('description')}")
                if espera:
                    time.sleep(int(espera) + 1)
            if enviados + fallos >= MAX_ENVIOS:
                log("Tope de envios por corrida alcanzado")
                break
            time.sleep(SEGUNDOS)
        if enviados + fallos >= MAX_ENVIOS:
            break

    log(f"Fin: {enviados} enviados, {fallos} fallos, {len(estado)} registrados en total")


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    main()