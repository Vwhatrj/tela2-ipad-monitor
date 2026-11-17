# -*- coding: utf-8 -*-
"""
Tela 2 - usa um iPad antigo (Safari do iOS 9) como tela extra do Windows.

Como funciona:
  - captura um monitor do Windows (de preferencia um monitor virtual);
  - comprime cada quadro em JPEG;
  - serve por HTTP simples na rede local, sem websocket e sem JavaScript moderno,
    para que o Safari antigo consiga exibir.

Uso rapido:
  python servidor.py --listar          # mostra os monitores encontrados
  python servidor.py                   # usa o monitor secundario de 1024x768 (o virtual)
  python servidor.py --monitor 1 --permitir-principal   # espelha a tela principal (teste)
"""
import argparse
import ctypes
import ctypes.wintypes
import hmac
import io
import secrets
import socket
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

try:
    import mss
    from PIL import Image, ImageDraw
except ImportError:
    print("Faltam bibliotecas. Rode:  python -m pip install mss pillow")
    sys.exit(1)

PASTA = Path(__file__).resolve().parent
# mss 10+ usa mss.MSS (mss.mss so gera aviso); versoes antigas so tem mss.mss.
abrir_captura = getattr(mss, "MSS", None) or mss.mss
LIMITE = "quadro"

# Seta do mouse (o mss captura a tela sem o ponteiro). Pontas em pixels, a partir da ponta da seta.
SETA = [(0, 0), (0, 17), (4, 13), (7, 20), (10, 19), (7, 12), (12, 12)]


def posicao_cursor():
    ponto = ctypes.wintypes.POINT()
    if not ctypes.windll.user32.GetCursorPos(ctypes.byref(ponto)):
        return None
    return ponto.x, ponto.y


def desenhar_cursor(img, area, pos):
    """Desenha uma seta onde o mouse esta, se ele estiver dentro do monitor capturado."""
    if pos is None:
        return
    x, y = pos[0] - area["left"], pos[1] - area["top"]
    if 0 <= x < area["width"] and 0 <= y < area["height"]:
        ImageDraw.Draw(img).polygon([(x + dx, y + dy) for dx, dy in SETA],
                                    fill=(255, 255, 255), outline=(0, 0, 0))


# Botoes do mouse para mouse_event (Windows).
MOUSE = {
    "baixo": (0x0002,), "cima": (0x0004,), "clique": (0x0002, 0x0004),
    "direito": (0x0008, 0x0010),
}


class MONITORINFO(ctypes.Structure):
    _fields_ = [("cbSize", ctypes.wintypes.DWORD), ("rcMonitor", ctypes.wintypes.RECT),
                ("rcWork", ctypes.wintypes.RECT), ("dwFlags", ctypes.wintypes.DWORD)]


_user32 = ctypes.windll.user32
_user32.MonitorFromPoint.argtypes = [ctypes.wintypes.POINT, ctypes.wintypes.DWORD]
_user32.MonitorFromPoint.restype = ctypes.c_void_p
_user32.GetMonitorInfoW.argtypes = [ctypes.c_void_p, ctypes.POINTER(MONITORINFO)]


def ponto_no_monitor(px, py, area, permitir_principal):
    """Confere, no proprio Windows, que (px, py) cai no monitor capturado e que ele
    nao e o principal. Se o monitor virtual sumir, o toque e recusado em vez de cair na tela principal."""
    hmon = _user32.MonitorFromPoint(ctypes.wintypes.POINT(px, py), 0)  # 0 = MONITOR_DEFAULTTONULL
    return monitor_confere(hmon, area, permitir_principal)


def monitor_confere(hmon, area, permitir_principal):
    """True se o monitor `hmon` e exatamente o capturado (e nao o principal, salvo permissao)."""
    if not hmon:
        return False
    info = MONITORINFO()
    info.cbSize = ctypes.sizeof(MONITORINFO)
    if not _user32.GetMonitorInfoW(hmon, ctypes.byref(info)):
        return False
    r = info.rcMonitor
    mesmo = (r.left, r.top, r.right - r.left, r.bottom - r.top) == (
        area["left"], area["top"], area["width"], area["height"])
    principal = bool(info.dwFlags & 1)  # MONITORINFOF_PRIMARY
    return mesmo and (permitir_principal or not principal)


def tocar(acao, x, y, area, permitir_principal=False):
    """Move o mouse para (x, y), de 0 a 1 dentro do monitor capturado, e aperta o botao pedido.
    Devolve False (sem mexer no mouse) se o ponto nao estiver no monitor capturado."""
    x, y = min(max(x, 0.0), 1.0), min(max(y, 0.0), 1.0)
    px = area["left"] + round(x * (area["width"] - 1))
    py = area["top"] + round(y * (area["height"] - 1))
    if not ponto_no_monitor(px, py, area, permitir_principal):
        return False
    _user32.SetCursorPos(px, py)
    for botao in MOUSE.get(acao, ()):
        _user32.mouse_event(botao, 0, 0, 0, 0)
    return True


# ---- Teclado (SendInput) ----

class KEYBDINPUT(ctypes.Structure):
    _fields_ = [("wVk", ctypes.wintypes.WORD), ("wScan", ctypes.wintypes.WORD),
                ("dwFlags", ctypes.wintypes.DWORD), ("time", ctypes.wintypes.DWORD),
                ("dwExtraInfo", ctypes.c_size_t)]


class MOUSEINPUT(ctypes.Structure):
    _fields_ = [("dx", ctypes.wintypes.LONG), ("dy", ctypes.wintypes.LONG),
                ("mouseData", ctypes.wintypes.DWORD), ("dwFlags", ctypes.wintypes.DWORD),
                ("time", ctypes.wintypes.DWORD), ("dwExtraInfo", ctypes.c_size_t)]


class _ENTRADA(ctypes.Union):
    _fields_ = [("ki", KEYBDINPUT), ("mi", MOUSEINPUT)]


class INPUT(ctypes.Structure):
    _fields_ = [("type", ctypes.wintypes.DWORD), ("u", _ENTRADA)]


_user32.SendInput.argtypes = [ctypes.wintypes.UINT, ctypes.POINTER(INPUT), ctypes.c_int]
_user32.GetForegroundWindow.restype = ctypes.c_void_p
_user32.MonitorFromWindow.argtypes = [ctypes.c_void_p, ctypes.wintypes.DWORD]
_user32.MonitorFromWindow.restype = ctypes.c_void_p

TECLADO, UNICODE, SOLTAR = 1, 0x0004, 0x0002
MAX_TEXTO = 200  # caracteres por pedido
TECLAS = {  # nome -> codigo virtual do Windows
    "enter": 0x0D, "apagar": 0x08, "tab": 0x09, "esc": 0x1B, "delete": 0x2E,
    "esquerda": 0x25, "cima": 0x26, "direita": 0x27, "baixo": 0x28,
}


def janela_ativa_no_monitor(area, permitir_principal=False):
    """Confere que a janela que vai receber as teclas esta no monitor capturado.
    Assim o iPad nunca digita numa janela da tela principal."""
    hwnd = _user32.GetForegroundWindow()
    if not hwnd:
        return False
    return monitor_confere(_user32.MonitorFromWindow(hwnd, 0), area, permitir_principal)


def _enviar_entradas(entradas):
    n = len(entradas)
    if n:
        _user32.SendInput(n, (INPUT * n)(*entradas), ctypes.sizeof(INPUT))


def digitar(texto, area, permitir_principal=False):
    """Digita `texto` (com acentos) na janela ativa, se ela estiver no monitor capturado."""
    if not janela_ativa_no_monitor(area, permitir_principal):
        return False
    entradas = []
    codigos = texto.encode("utf-16-le")
    for i in range(0, len(codigos), 2):
        unidade = int.from_bytes(codigos[i:i + 2], "little")
        for flags in (UNICODE, UNICODE | SOLTAR):
            entradas.append(INPUT(type=TECLADO, u=_ENTRADA(ki=KEYBDINPUT(0, unidade, flags, 0, 0))))
    _enviar_entradas(entradas)
    return True


def apertar_tecla(nome, area, permitir_principal=False):
    """Aperta uma tecla especial (Enter, apagar, setas...) na janela ativa do monitor capturado."""
    if not janela_ativa_no_monitor(area, permitir_principal):
        return False
    vk = TECLAS[nome]
    _enviar_entradas([INPUT(type=TECLADO, u=_ENTRADA(ki=KEYBDINPUT(vk, 0, f, 0, 0))) for f in (0, SOLTAR)])
    return True


class Bloqueio:
    """Bloqueia por alguns minutos o IP que errar a chave varias vezes seguidas."""

    def __init__(self, tentativas=5, minutos=5):
        self.tentativas = tentativas
        self.segundos = minutos * 60
        self.trava = threading.Lock()
        self.erros = {}       # ip -> erros seguidos
        self.ate = {}         # ip -> horario em que o bloqueio acaba

    def bloqueado(self, ip):
        with self.trava:
            return self.ate.get(ip, 0) > time.time()

    def errou(self, ip):
        with self.trava:
            self.erros[ip] = self.erros.get(ip, 0) + 1
            if self.erros[ip] >= self.tentativas:
                self.erros[ip] = 0
                self.ate[ip] = time.time() + self.segundos
                print("Bloqueado por {} min: {} (chave errada {} vezes).".format(
                    self.segundos // 60, ip, self.tentativas), flush=True)

    def acertou(self, ip):
        with self.trava:
            self.erros.pop(ip, None)


class Capturador(threading.Thread):
    """Captura o monitor escolhido em loop e guarda sempre o quadro mais recente."""

    def __init__(self, monitor, largura, qualidade, fps):
        super().__init__(daemon=True)
        self.monitor = monitor
        self.largura = largura
        self.qualidade = qualidade
        self.intervalo = 1.0 / max(1, fps)
        self.cond = threading.Condition()
        self.jpeg = None
        self.numero = 0
        self.ultimo_pedido = 0.0
        self.area = None  # posicao do monitor na area de trabalho (usada pelo toque)

    def run(self):
        with abrir_captura() as sct:
            area = sct.monitors[self.monitor]
            self.area = area
            anterior = None  # (pixels, cursor) do ultimo quadro enviado
            while True:
                # Ninguem assistindo ha alguns segundos: descansa e nao gasta CPU.
                if time.time() - self.ultimo_pedido > 5:
                    time.sleep(0.2)
                    continue

                inicio = time.perf_counter()
                bruto = sct.grab(area)
                pos = posicao_cursor()
                # Tela parada: nao comprime nem envia de novo (economiza CPU, Wi-Fi e bateria do iPad).
                if anterior is not None and anterior[1] == pos and anterior[0] == bruto.raw:
                    time.sleep(self.intervalo)
                    continue
                anterior = (bruto.raw, pos)
                img = Image.frombytes("RGB", bruto.size, bruto.bgra, "raw", "BGRX")
                desenhar_cursor(img, area, pos)
                if self.largura and img.width > self.largura:
                    altura = round(img.height * self.largura / img.width)
                    img = img.resize((self.largura, altura), Image.BILINEAR)

                buf = io.BytesIO()
                img.save(buf, "JPEG", quality=self.qualidade)

                with self.cond:
                    self.jpeg = buf.getvalue()
                    self.numero += 1
                    self.cond.notify_all()

                sobra = self.intervalo - (time.perf_counter() - inicio)
                if sobra > 0:
                    time.sleep(sobra)

    def proximo(self, ultimo, espera=3.0):
        """Espera um quadro diferente de `ultimo` e devolve (numero, jpeg)."""
        self.ultimo_pedido = time.time()
        with self.cond:
            self.cond.wait_for(lambda: self.numero != ultimo, espera)
            return self.numero, self.jpeg


def gerar_icone():
    """Icone simples para a Tela de Inicio do iPad (um monitor estilizado)."""
    lado = 152
    img = Image.new("RGB", (lado, lado), (18, 18, 20))
    d = ImageDraw.Draw(img)
    d.rectangle([24, 34, 128, 104], outline=(255, 176, 32), width=8)
    d.rectangle([68, 104, 84, 118], fill=(255, 176, 32))
    d.rectangle([48, 118, 104, 126], fill=(255, 176, 32))
    buf = io.BytesIO()
    img.save(buf, "PNG")
    return buf.getvalue()


class Pedido(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"  # keep-alive: reaproveita a conexao em vez de abrir uma por quadro
    capturador = None
    icone = b""
    chave = ""  # exigida em ?chave= (menos no icone)
    enviados = 0  # quadros entregues ao iPad (para medir o fps real)
    bloqueio = Bloqueio()
    permitir_principal = False

    def log_message(self, *args):
        pass  # silencia o log de cada requisicao

    def do_GET(self):
        url = urlparse(self.path)
        caminho = url.path
        try:
            q = parse_qs(url.query)
            # Pagina e icone ficam liberados (a pagina avisa se faltar a chave);
            # imagem e toque exigem ?chave= correta.
            if caminho in ("/", "/index.html"):
                self.enviar_arquivo(PASTA / "index.html", "text/html; charset=utf-8")
                return
            if caminho in ("/icone.png", "/apple-touch-icon.png"):
                self.enviar_bytes(self.icone, "image/png")
                return
            ip = self.client_address[0]
            if self.bloqueio.bloqueado(ip):
                self.recusar(429)
                return
            if not hmac.compare_digest(q.get("chave", [""])[0], self.chave):
                self.bloqueio.errou(ip)
                self.recusar()
                return
            self.bloqueio.acertou(ip)
            if caminho == "/toque":
                self.receber_toque(q)
            elif caminho == "/tecla":
                self.receber_tecla(q)
            elif caminho == "/frame.jpg":
                self.enviar_quadro()
            elif caminho == "/stream.mjpg":
                self.enviar_stream()
            else:
                self.send_error(404)
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
            pass  # o iPad fechou a conexao; normal

    def recusar(self, codigo=403):
        if codigo == 429:
            texto = "Muitas tentativas com chave errada. Espere alguns minutos."
        else:
            texto = ("Acesso negado. Abra o endere&ccedil;o completo, com <b>?chave=</b>, "
                     "que aparece na janela do servidor no PC.")
        dados = ("<meta charset='utf-8'><body style='background:#000;color:#ddd;font:18px Helvetica'>"
                 "<p>" + texto + "</p>").encode("utf-8")
        self.send_response(codigo)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(dados)))
        self.end_headers()
        self.wfile.write(dados)

    def receber_toque(self, q):
        """/toque?a=baixo|cima|clique|direito|mover&x=0..1&y=0..1 (enviado pela pagina do iPad)."""
        area = self.capturador.area
        try:
            acao = q["a"][0]
            x, y = float(q["x"][0]), float(q["y"][0])
        except (KeyError, ValueError):
            self.send_error(400)
            return
        if area and acao in ("mover", "baixo", "cima", "clique", "direito"):
            if not tocar(acao, x, y, area, self.permitir_principal):
                self.send_error(409, "O monitor capturado nao esta mais disponivel")
                return
        self.responder_vazio()

    def receber_tecla(self, q):
        """/tecla?t=texto (digita, com acentos) ou /tecla?k=enter|apagar|tab|esc|delete|setas.
        So digita se a janela ativa estiver no monitor capturado (409 se nao estiver)."""
        area = self.capturador.area
        texto = q.get("t", [""])[0]
        nome = q.get("k", [""])[0]
        if texto:
            if len(texto) > MAX_TEXTO or any(ord(c) < 32 or ord(c) == 127 for c in texto):
                self.send_error(400, "Texto invalido")
                return
            feito = bool(area) and digitar(texto, area, self.permitir_principal)
        elif nome in TECLAS:
            feito = bool(area) and apertar_tecla(nome, area, self.permitir_principal)
        else:
            self.send_error(400, "Informe t= (texto) ou k= (tecla)")
            return
        if not feito:
            self.send_error(409, "A janela ativa nao esta no monitor do iPad")
            return
        self.responder_vazio()

    def responder_vazio(self):
        self.send_response(204)
        self.send_header("Content-Length", "0")
        self.send_header("Cache-Control", "no-cache, no-store")
        self.end_headers()

    def enviar_bytes(self, dados, tipo, cache=True):
        self.send_response(200)
        self.send_header("Content-Type", tipo)
        self.send_header("Content-Length", str(len(dados)))
        if not cache:
            self.send_header("Cache-Control", "no-cache, no-store")
        self.end_headers()
        self.wfile.write(dados)

    def enviar_arquivo(self, arquivo, tipo):
        self.enviar_bytes(arquivo.read_bytes(), tipo, cache=False)

    def enviar_quadro(self):
        # Sempre espera o PROXIMO quadro, para nao mandar a mesma imagem duas vezes.
        _, dados = self.capturador.proximo(self.capturador.numero)
        if dados is None:
            self.send_error(503, "Ainda sem imagem")
            return
        self.enviar_bytes(dados, "image/jpeg", cache=False)
        Pedido.enviados += 1

    def enviar_stream(self):
        self.send_response(200)
        self.send_header("Content-Type", "multipart/x-mixed-replace; boundary=" + LIMITE)
        self.send_header("Cache-Control", "no-cache, no-store")
        self.end_headers()
        numero = 0
        while True:
            numero, dados = self.capturador.proximo(numero)
            if dados is None:
                continue
            cabecalho = (
                "--{}\r\nContent-Type: image/jpeg\r\nContent-Length: {}\r\n\r\n"
                .format(LIMITE, len(dados))
            )
            self.wfile.write(cabecalho.encode("ascii"))
            self.wfile.write(dados)
            self.wfile.write(b"\r\n")
            Pedido.enviados += 1


def medidor():
    """Imprime a cada 5 s quantos quadros por segundo o iPad esta recebendo."""
    anterior = 0
    while True:
        time.sleep(5)
        atual = Pedido.enviados
        if atual != anterior:
            print("iPad recebendo: {:.1f} quadros/s".format((atual - anterior) / 5.0), flush=True)
        anterior = atual


def ip_local():
    """IP do PC na rede de casa (o que vai no Safari do iPad)."""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("8.8.8.8", 80))  # nao envia nada; so descobre a interface da rota padrao
        return s.getsockname()[0]
    except OSError:
        return "127.0.0.1"
    finally:
        s.close()


def carregar_chave(escolhida):
    """Chave da URL. Fica salva em chave.txt para o icone do iPad continuar valendo."""
    arquivo = PASTA / "chave.txt"
    if escolhida:
        chave = escolhida.strip()
    elif arquivo.exists() and arquivo.read_text(encoding="utf-8").strip():
        return arquivo.read_text(encoding="utf-8").strip()
    else:
        chave = str(secrets.randbelow(900000) + 100000)  # 6 digitos, facil de digitar no iPad
    arquivo.write_text(chave, encoding="utf-8")
    return chave


TAMANHO_IPAD = (1024, 768)


def principal(m):
    """No Windows, o monitor principal e sempre o que comeca na posicao (0, 0)."""
    return m["left"] == 0 and m["top"] == 0


def listar_monitores():
    with abrir_captura() as sct:
        monitores = sct.monitors[1:]
    for i, m in enumerate(monitores, start=1):
        if principal(m):
            papel = "PRINCIPAL (nao use no iPad)"
        elif (m["width"], m["height"]) == TAMANHO_IPAD:
            papel = "secundario 1024x768 (provavelmente o monitor virtual do iPad)"
        else:
            papel = "secundario"
        print("  Monitor {}: {}x{}  (posicao {}, {})  {}".format(
            i, m["width"], m["height"], m["left"], m["top"], papel))
    return monitores


def escolher_monitor(monitores, pedido, permitir_principal):
    """Devolve o numero do monitor a transmitir, ou encerra explicando o motivo.
    Por padrao nunca usa o principal: se o monitor virtual sumir (atualizacao do Windows,
    driver novo), o servidor nao inicia em vez de mostrar e clicar na tela de verdade."""
    if pedido is not None:
        if not 1 <= pedido <= len(monitores):
            sys.exit("Monitor {} nao existe. Escolha entre 1 e {}.".format(pedido, len(monitores)))
        if principal(monitores[pedido - 1]) and not permitir_principal:
            sys.exit("O monitor {} e o PRINCIPAL. Para espelhar a tela principal de proposito "
                     "(o toque vai clicar nela), use tambem --permitir-principal.".format(pedido))
        return pedido
    secundarios = [i for i, m in enumerate(monitores, start=1) if not principal(m)]
    do_ipad = [i for i in secundarios if (monitores[i - 1]["width"], monitores[i - 1]["height"]) == TAMANHO_IPAD]
    if not do_ipad:
        sys.exit("Nao achei um monitor secundario de 1024x768 (o monitor virtual do iPad).\n"
                 "Confira se o driver de monitor virtual esta ativo e em 1024x768 "
                 "(Configuracoes > Sistema > Tela), ou escolha um com --monitor N.")
    return do_ipad[-1]


def main():
    p = argparse.ArgumentParser(description="Tela 2 - iPad antigo como tela extra do Windows")
    p.add_argument("--porta", type=int, default=8080)
    p.add_argument("--monitor", type=int, default=None,
                   help="numero do monitor (padrao: o secundario de 1024x768, o virtual)")
    p.add_argument("--permitir-principal", action="store_true",
                   help="deixa transmitir e clicar no monitor principal (so para teste de espelhamento)")
    p.add_argument("--largura", type=int, default=1024,
                   help="largura maxima da imagem enviada (padrao 1024)")
    p.add_argument("--qualidade", type=int, default=75, help="qualidade JPEG 1-95 (padrao 75)")
    p.add_argument("--fps", type=int, default=30, help="quadros por segundo maximos (padrao 30)")
    p.add_argument("--listar", action="store_true", help="so lista os monitores e sai")
    p.add_argument("--chave", default=None,
                   help="chave exigida na URL (padrao: a salva em chave.txt, criada na 1a vez)")
    args = p.parse_args()

    print("Monitores encontrados:")
    monitores = listar_monitores()
    if args.listar:
        return

    monitor = escolher_monitor(monitores, args.monitor, args.permitir_principal)
    Pedido.permitir_principal = args.permitir_principal

    capturador = Capturador(monitor, args.largura, max(1, min(95, args.qualidade)), args.fps)
    capturador.start()
    Pedido.capturador = capturador
    Pedido.icone = gerar_icone()
    Pedido.chave = carregar_chave(args.chave)

    servidor = ThreadingHTTPServer(("0.0.0.0", args.porta), Pedido)
    servidor.daemon_threads = True
    threading.Thread(target=medidor, daemon=True).start()

    endereco = "http://{}:{}/?chave={}".format(ip_local(), args.porta, Pedido.chave)
    print()
    print("Transmitindo o monitor {}.".format(monitor))
    print("No Safari do iPad, abra:  {}".format(endereco))
    print("Modo alternativo (stream continuo):  {}&modo=mjpeg".format(endereco))
    print("Para parar, feche esta janela ou aperte Ctrl+C.")
    try:
        servidor.serve_forever()
    except KeyboardInterrupt:
        print("\nEncerrado.")


if __name__ == "__main__":
    main()
