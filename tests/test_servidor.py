# -*- coding: utf-8 -*-
"""
Testes do Tela 2 (so biblioteca padrao: python -m unittest discover -s tests -v).

Nenhum teste clica de verdade: a funcao que mexe no mouse e trocada por uma
que so anota as chamadas, e a captura de tela e substituida por um quadro falso.
Precisa de Windows (o servidor usa a API Win32).
"""
import ctypes
import ctypes.wintypes
import re
import sys
import tempfile
import threading
import unittest
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))

import servidor  # noqa: E402

CHAVE = "123456"
JPEG_FALSO = b"\xff\xd8\xff\xe0quadro-de-teste\xff\xd9"
AREA_VIRTUAL = {"left": 1920, "top": 0, "width": 1024, "height": 768}


class CapturadorFalso:
    """Faz o papel do Capturador sem capturar a tela."""
    numero = 1
    area = AREA_VIRTUAL

    def proximo(self, ultimo, espera=3.0):
        return 1, JPEG_FALSO


class TesteHTTP(unittest.TestCase):
    """Sobe o servidor de verdade numa porta livre, com captura e clique falsos."""

    @classmethod
    def setUpClass(cls):
        servidor.Pedido.capturador = CapturadorFalso()
        servidor.Pedido.chave = CHAVE
        servidor.Pedido.icone = b"\x89PNG-teste"
        cls.http = servidor.ThreadingHTTPServer(("127.0.0.1", 0), servidor.Pedido)
        cls.http.daemon_threads = True
        cls.base = "http://127.0.0.1:{}".format(cls.http.server_address[1])
        threading.Thread(target=cls.http.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.http.shutdown()
        cls.http.server_close()

    def setUp(self):
        servidor.Pedido.bloqueio = servidor.Bloqueio(tentativas=5, minutos=5)
        self.toques = []
        self.toque_aceito = True
        self._tocar_original = servidor.tocar

        def tocar_falso(acao, x, y, area, permitir_principal=False):
            self.toques.append((acao, x, y))
            return self.toque_aceito
        servidor.tocar = tocar_falso

        # Teclado falso: so anota (nunca digita de verdade).
        self.digitado = []
        self.janela_no_ipad = True
        self._digitar_original = servidor.digitar
        self._tecla_original = servidor.apertar_tecla

        def digitar_falso(texto, area, permitir_principal=False):
            if self.janela_no_ipad:
                self.digitado.append(("texto", texto))
            return self.janela_no_ipad

        def tecla_falsa(nome, area, permitir_principal=False):
            if self.janela_no_ipad:
                self.digitado.append(("tecla", nome))
            return self.janela_no_ipad
        servidor.digitar = digitar_falso
        servidor.apertar_tecla = tecla_falsa

    def tearDown(self):
        servidor.tocar = self._tocar_original
        servidor.digitar = self._digitar_original
        servidor.apertar_tecla = self._tecla_original

    def get(self, caminho):
        """Devolve (status, corpo, content-type)."""
        try:
            with urllib.request.urlopen(self.base + caminho, timeout=5) as r:
                return r.status, r.read(), r.headers.get("Content-Type", "")
        except urllib.error.HTTPError as e:
            return e.code, e.read(), e.headers.get("Content-Type", "")

    # Pagina e icone ficam liberados
    def test_pagina_abre_sem_chave(self):
        status, corpo, tipo = self.get("/")
        self.assertEqual(status, 200)
        self.assertIn("text/html", tipo)
        self.assertIn(b"Tela 2", corpo)

    def test_icone_abre_sem_chave(self):
        self.assertEqual(self.get("/apple-touch-icon.png")[0], 200)

    # Imagem exige chave
    def test_quadro_sem_chave_da_403(self):
        self.assertEqual(self.get("/frame.jpg")[0], 403)

    def test_quadro_com_chave_errada_da_403(self):
        self.assertEqual(self.get("/frame.jpg?chave=000000")[0], 403)

    def test_quadro_com_chave_certa_devolve_jpeg(self):
        status, corpo, tipo = self.get("/frame.jpg?chave=" + CHAVE)
        self.assertEqual(status, 200)
        self.assertEqual(tipo, "image/jpeg")
        self.assertEqual(corpo, JPEG_FALSO)

    def test_stream_com_chave_errada_da_403(self):
        # Le so o status: se a trava quebrar, o stream e infinito e ler o corpo travaria o teste.
        try:
            with urllib.request.urlopen(self.base + "/stream.mjpg?chave=000000", timeout=5) as r:
                status = r.status
        except urllib.error.HTTPError as e:
            status = e.code
        self.assertEqual(status, 403)

    # Toque exige chave e nunca clica sem ela
    def test_toque_sem_chave_nao_clica(self):
        self.assertEqual(self.get("/toque?a=clique&x=0.5&y=0.5")[0], 403)
        self.assertEqual(self.toques, [])

    def test_toque_com_chave_errada_nao_clica(self):
        self.assertEqual(self.get("/toque?chave=000000&a=clique&x=0.5&y=0.5")[0], 403)
        self.assertEqual(self.toques, [])

    def test_toque_com_chave_certa_clica(self):
        self.assertEqual(self.get("/toque?chave={}&a=clique&x=0.25&y=0.75".format(CHAVE))[0], 204)
        self.assertEqual(self.toques, [("clique", 0.25, 0.75)])

    def test_acao_desconhecida_nao_clica(self):
        self.assertEqual(self.get("/toque?chave={}&a=verificar&x=0&y=0".format(CHAVE))[0], 204)
        self.assertEqual(self.toques, [])

    def test_toque_sem_coordenadas_da_400(self):
        self.assertEqual(self.get("/toque?chave={}&a=clique".format(CHAVE))[0], 400)
        self.assertEqual(self.toques, [])

    def test_toque_fora_do_monitor_da_409(self):
        self.toque_aceito = False  # como se o monitor virtual tivesse sumido
        self.assertEqual(self.get("/toque?chave={}&a=clique&x=0.5&y=0.5".format(CHAVE))[0], 409)

    # Limite de tentativas
    def test_cinco_erros_bloqueiam_mesmo_com_chave_certa(self):
        for _ in range(4):
            self.assertEqual(self.get("/frame.jpg?chave=000000")[0], 403)
        self.assertEqual(self.get("/frame.jpg?chave=" + CHAVE)[0], 200, "4 erros ainda nao bloqueiam")
        for _ in range(5):
            self.get("/frame.jpg?chave=000000")
        self.assertEqual(self.get("/frame.jpg?chave=" + CHAVE)[0], 429)
        self.assertEqual(self.get("/toque?chave={}&a=clique&x=0.5&y=0.5".format(CHAVE))[0], 429)
        self.assertEqual(self.toques, [], "bloqueado nao pode clicar")

    # Teclado
    def test_tecla_sem_chave_nao_digita(self):
        self.assertEqual(self.get("/tecla?t=oi")[0], 403)
        self.assertEqual(self.get("/tecla?chave=000000&k=enter")[0], 403)
        self.assertEqual(self.digitado, [])

    def test_texto_com_acentos_e_digitado(self):
        texto = urllib.parse.quote("Olá, ação! 1+1")
        self.assertEqual(self.get("/tecla?chave={}&t={}".format(CHAVE, texto))[0], 204)
        self.assertEqual(self.digitado, [("texto", "Olá, ação! 1+1")])

    def test_teclas_especiais(self):
        for nome in ("enter", "apagar", "tab", "esc", "esquerda"):
            self.assertEqual(self.get("/tecla?chave={}&k={}".format(CHAVE, nome))[0], 204)
        self.assertEqual([n for _, n in self.digitado], ["enter", "apagar", "tab", "esc", "esquerda"])

    def test_tecla_desconhecida_ou_vazia_da_400(self):
        self.assertEqual(self.get("/tecla?chave={}&k=desligar".format(CHAVE))[0], 400)
        self.assertEqual(self.get("/tecla?chave={}".format(CHAVE))[0], 400)
        self.assertEqual(self.digitado, [])

    def test_texto_com_caractere_de_controle_da_400(self):
        self.assertEqual(self.get("/tecla?chave={}&t=a%0Db".format(CHAVE))[0], 400)
        self.assertEqual(self.digitado, [])

    def test_texto_grande_demais_da_400(self):
        self.assertEqual(self.get("/tecla?chave={}&t={}".format(CHAVE, "a" * 201))[0], 400)
        self.assertEqual(self.get("/tecla?chave={}&t={}".format(CHAVE, "a" * 200))[0], 204)

    def test_janela_fora_do_ipad_da_409_e_nao_digita(self):
        self.janela_no_ipad = False
        self.assertEqual(self.get("/tecla?chave={}&t=segredo".format(CHAVE))[0], 409)
        self.assertEqual(self.get("/tecla?chave={}&k=enter".format(CHAVE))[0], 409)
        self.assertEqual(self.digitado, [])

    def test_rota_desconhecida_da_404(self):
        self.assertEqual(self.get("/nada?chave=" + CHAVE)[0], 404)


class TesteBloqueio(unittest.TestCase):
    def test_conta_por_ip_e_zera_ao_acertar(self):
        b = servidor.Bloqueio(tentativas=5, minutos=5)
        for _ in range(4):
            b.errou("10.0.0.1")
        b.acertou("10.0.0.1")
        for _ in range(4):
            b.errou("10.0.0.1")
        self.assertFalse(b.bloqueado("10.0.0.1"), "acertar zera a contagem")
        b.errou("10.0.0.1")
        self.assertTrue(b.bloqueado("10.0.0.1"))
        self.assertFalse(b.bloqueado("10.0.0.2"), "outro IP nao e afetado")


class TesteEscolhaDoMonitor(unittest.TestCase):
    PRINCIPAL = {"left": 0, "top": 0, "width": 1920, "height": 1080}
    VIRTUAL = AREA_VIRTUAL

    def escolher(self, monitores, pedido=None, permitir=False):
        return servidor.escolher_monitor(monitores, pedido, permitir)

    def test_padrao_usa_o_secundario_1024x768(self):
        self.assertEqual(self.escolher([self.PRINCIPAL, self.VIRTUAL]), 2)

    def test_sem_monitor_virtual_nao_inicia(self):
        with self.assertRaises(SystemExit):
            self.escolher([self.PRINCIPAL])

    def test_secundario_de_outro_tamanho_nao_e_usado_por_padrao(self):
        with self.assertRaises(SystemExit):
            self.escolher([self.PRINCIPAL, dict(self.VIRTUAL, width=1920, height=1080)])

    def test_principal_pedido_e_recusado(self):
        with self.assertRaises(SystemExit):
            self.escolher([self.PRINCIPAL, self.VIRTUAL], pedido=1)

    def test_principal_com_permissao_explicita(self):
        self.assertEqual(self.escolher([self.PRINCIPAL, self.VIRTUAL], pedido=1, permitir=True), 1)

    def test_monitor_inexistente(self):
        with self.assertRaises(SystemExit):
            self.escolher([self.PRINCIPAL, self.VIRTUAL], pedido=5)


class TesteTravaDoToque(unittest.TestCase):
    """Usa a API real do Windows, mas so com um monitor que nao existe: nada e clicado."""
    INEXISTENTE = {"left": 900000, "top": 900000, "width": 1024, "height": 768}

    def posicao(self):
        p = ctypes.wintypes.POINT()
        ctypes.windll.user32.GetCursorPos(ctypes.byref(p))
        return p.x, p.y

    def test_ponto_fora_de_qualquer_monitor_e_recusado(self):
        self.assertFalse(servidor.ponto_no_monitor(900010, 900010, self.INEXISTENTE, False))

    def test_digitar_em_monitor_que_sumiu_e_recusado(self):
        # Nenhuma janela esta num monitor inexistente: a trava recusa antes de digitar.
        self.assertFalse(servidor.janela_ativa_no_monitor(self.INEXISTENTE))
        self.assertFalse(servidor.digitar("nao-deve-aparecer", self.INEXISTENTE))
        self.assertFalse(servidor.apertar_tecla("enter", self.INEXISTENTE))

    def test_estrutura_do_sendinput(self):
        # O Windows recusa o SendInput se o tamanho da estrutura estiver errado.
        self.assertEqual(ctypes.sizeof(servidor.INPUT), 40 if ctypes.sizeof(ctypes.c_void_p) == 8 else 28)

    def test_tocar_em_monitor_que_sumiu_nao_mexe_no_mouse(self):
        antes = self.posicao()
        self.assertFalse(servidor.tocar("clique", 0.5, 0.5, self.INEXISTENTE))
        self.assertEqual(self.posicao(), antes)


class TesteChave(unittest.TestCase):
    def setUp(self):
        self.pasta_original = servidor.PASTA
        self.tmp = tempfile.TemporaryDirectory()
        servidor.PASTA = Path(self.tmp.name)

    def tearDown(self):
        servidor.PASTA = self.pasta_original
        self.tmp.cleanup()

    def test_cria_seis_digitos_e_reutiliza(self):
        primeira = servidor.carregar_chave(None)
        self.assertRegex(primeira, r"^\d{6}$")
        self.assertEqual(servidor.carregar_chave(None), primeira)

    def test_chave_escolhida_substitui_a_salva(self):
        servidor.carregar_chave(None)
        self.assertEqual(servidor.carregar_chave("4321"), "4321")
        self.assertEqual(servidor.carregar_chave(None), "4321")


class TesteES5(unittest.TestCase):
    """O index.html precisa rodar no Safari do iOS 9: nada de JavaScript moderno."""

    def test_index_html_sem_sintaxe_moderna(self):
        html = (RAIZ / "index.html").read_text(encoding="utf-8")
        script = "\n".join(re.findall(r"<script>(.*?)</script>", html, re.S))
        self.assertTrue(script.strip(), "nao achei o script do index.html")
        proibidos = {
            r"\blet\b": "let", r"\bconst\b": "const", r"=>": "arrow function",
            r"\bfetch\s*\(": "fetch", r"\bPromise\b": "Promise", r"\bclass\b": "class",
            r"`": "template string", r"\bWebSocket\b": "WebSocket",
        }
        for padrao, nome in proibidos.items():
            self.assertIsNone(re.search(padrao, script), "index.html usa " + nome)


if __name__ == "__main__":
    unittest.main()
