# Tela 2 — um iPad 3 como segundo monitor do Windows

[![Testes](https://github.com/Vwhatrj/tela2-ipad-monitor/actions/workflows/testes.yml/badge.svg)](https://github.com/Vwhatrj/tela2-ipad-monitor/actions/workflows/testes.yml)

O iPad 3 (2012) tem processador de 32 bits e está preso no iOS 9.3.6. Apps de segundo monitor
como o Spacedesk não instalam (são só 64 bits), e a versão pelo navegador falha porque o Safari
do iOS 9 não aguenta o WebSocket e o JavaScript moderno que ela usa.

O **Tela 2** contorna isso com o mínimo possível: um servidor em Python captura um monitor virtual
do Windows, comprime cada quadro em **JPEG** e serve por **HTTP simples** na rede local. Do lado do
iPad, uma página em **JavaScript ES5** troca as imagens quadro a quadro e devolve os toques como cliques.
Nada é instalado no iPad.

<!-- GIF de demonstração: salve em docs/demo.gif e tire os marcadores de comentário da linha abaixo.
![Tela 2 funcionando: janela arrastada para o iPad e toque](docs/demo.gif)
-->

**Resultado testado:** monitor estendido em 1024 × 768, média de **~17 quadros/s**, **30 minutos
seguidos sem travar**, toque funcionando (clique, arrastar e botão direito) e teclado do iPad digitando no PC.

## Como funciona

```
 Windows                                          iPad 3 (Safari, iOS 9)
┌──────────────────────────────┐                ┌──────────────────────────┐
│ monitor virtual (1024 × 768) │                │ index.html (ES5)         │
│        │ captura (mss)       │   HTTP/1.1     │                          │
│        ▼                     │  keep-alive    │ <img> trocada a cada     │
│ desenha o cursor + JPEG      │ ─────────────► │ quadro (/frame.jpg)      │
│ (Pillow)                     │                │                          │
│        │                     │                │ toque → XMLHttpRequest   │
│ servidor HTTP :8080          │ ◄───────────── │ /toque?a=clique&x=…&y=…  │
│        │                     │                └──────────────────────────┘
│        ▼                     │
│ move/clica o mouse (Win32)   │
└──────────────────────────────┘
```

- **Sem WebSocket:** o iPad pede um quadro por vez (`/frame.jpg`) e já pede o próximo quando ele chega.
  Há também um modo de stream contínuo (`multipart/x-mixed-replace`), com `&modo=mjpeg`.
- **Keep-alive:** o servidor responde em HTTP/1.1 e reaproveita a conexão, em vez de abrir uma por quadro.
- **Toque:** uma camada fixa transparente recebe os toques (a imagem é trocada a cada quadro, e o iOS
  perde o gesto se o elemento tocado sai da página). Os toques vão em fila, um pedido por vez.
- **Tela parada não é reenviada:** se os pixels e o cursor não mudaram, o servidor nem comprime o quadro.
- **Segurança:** chave na URL (comparada em tempo constante), bloqueio após 5 erros, nunca a tela
  principal e toque conferido no Windows antes de cada clique (detalhes em [Segurança](#segurança)).

## Requisitos

- Windows 10/11 com **Python 3** (marque "Add python.exe to PATH" no instalador).
- Bibliotecas: `pip install -r requirements.txt` (mss e Pillow). O `iniciar.bat` já faz isso.
- PC e iPad na mesma rede.
- Um driver de monitor virtual. Usei o **[Virtual Display Driver](https://github.com/VirtualDrivers/Virtual-Display-Driver)**,
  projeto open source da organização **VirtualDrivers** (não incluído neste repositório).

## 1. Preparar o PC (uma vez só)

1. Deixe a rede de casa como **Rede privada**: Configurações > Rede e Internet > Ethernet (ou Wi-Fi) >
   Tipo de perfil de rede > **Rede privada**. Confira mesmo que ache que já está: o Windows pode
   marcar a rede de casa como Pública e uma VPN (Radmin, por exemplo) como Privada.
2. Libere a porta no firewall só para a rede local. No **Prompt de Comando como administrador**:

   ```
   netsh advfirewall firewall add rule name="Tela 2" dir=in action=allow protocol=TCP localport=8080 profile=private remoteip=localsubnet
   ```

   O `remoteip=localsubnet` impede acessos vindos de outras redes privadas, como a de uma VPN.

## 2. Monitor virtual (tela estendida)

1. Baixe o Virtual Display Driver na [página de releases oficial](https://github.com/VirtualDrivers/Virtual-Display-Driver/releases).
   Num PC Intel/AMD, use o pacote **x64**, não o ARM64. Siga as instruções do próprio projeto; com o pacote
   manual, os passos foram:
   - `installCert.bat` > **Executar como administrador**;
   - **Gerenciador de Dispositivos** > **Ação > Adicionar hardware herdado** > instalar manualmente >
     **Adaptadores de vídeo** > **Com disco...** > `MttVDD.inf`.
2. **Resolução 1024 × 768** (mesmo formato 4:3 do iPad): o driver lê as resoluções de
   `C:\VirtualDisplayDriver\vdd_settings.xml`. Sem esse arquivo, ele usa uma lista própria sem 1024 × 768.
   Copie o `vdd_settings.xml` do pacote para essa pasta e acrescente, dentro de `<resolutions>`:

   ```xml
   <resolution>
       <width>1024</width>
       <height>768</height>
       <refresh_rate>30</refresh_rate>
       <refresh_rate>60</refresh_rate>
   </resolution>
   ```

   Depois, no Gerenciador de Dispositivos, **Desabilitar** e **Habilitar** o "Virtual Display Driver".
3. Em **Configurações > Sistema > Tela**: **"Estender estas telas"**, posicione o monitor virtual do lado
   em que o iPad fica e escolha **1024 × 768**.

## 3. Usar

1. Dê dois cliques em **`iniciar.bat`**. Sem opções, ele usa o **monitor secundário de 1024 × 768**
   (o virtual), **30 fps** e **qualidade 75**. Se esse monitor não existir (por exemplo, o driver sumiu
   depois de uma atualização do Windows), **o servidor não inicia**, em vez de mostrar e clicar na sua
   tela principal.
2. A janela mostra o endereço com a chave, por exemplo `http://192.168.0.10:8080/?chave=123456`,
   e a cada 5 s mostra `iPad recebendo: X quadros/s`.
3. No iPad, abra esse endereço no Safari e toque em **Compartilhar > "Adicionar à Tela de Início"**.
   Abra **sempre pelo ícone Tela 2**: assim abre em tela cheia, sem a barra do Safari.
4. No iPad, em **Ajustes > Geral > Bloqueio Automático**, escolha **Nunca** (e deixe na tomada).

**Sempre que mudar a resolução do monitor virtual, reinicie o `iniciar.bat`.** O servidor guarda o
tamanho da tela quando começa. Para ver os monitores e qual é o principal: `iniciar.bat --listar`.

Com a tela parada, o servidor não reenvia a mesma imagem: manda de novo só a cada ~3 s, para manter a
conexão. Por isso o `iPad recebendo` cai para perto de zero quando nada se mexe; é o esperado.

### Abrir sozinho com o Windows

- **Ligar:** dois cliques em **`ligar-com-windows.bat`**. Ele põe um atalho do `iniciar.bat` na pasta
  Inicializar do seu usuário (não precisa de administrador). Ao entrar no Windows, o Tela 2 abre
  **minimizado** na barra de tarefas; abra a janela se precisar ver o endereço com a chave.
- **Desligar:** dois cliques em **`desligar-com-windows.bat`**. Ele apaga só esse atalho.

Se o monitor virtual não estiver pronto quando o Windows abrir, o servidor avisa e não inicia (é a
trava de segurança); nesse caso, feche a janela e rode o `iniciar.bat` de novo.

### Toque

| No iPad | No PC (monitor virtual) |
|---|---|
| Tocar | Clique esquerdo |
| Arrastar o dedo | Segura o clique e arrasta (janelas, barra do vídeo, seleção) |
| Segurar parado ~0,6 s | Clique direito |

É o mouse de verdade do PC que se move. O ponteiro aparece no iPad como uma seta branca.

### Teclado

1. Toque numa janela que esteja no monitor virtual (uma caixa de texto, por exemplo).
2. Toque em **"Teclado"**, no canto inferior direito: o teclado do iPad abre e o botão sobe para o
   canto superior.
3. Digite. Letras, acentos, apagar e Enter chegam ao PC (Tab e setas também, num teclado externo). A imagem é deslocada para mostrar, acima do
   teclado, a região onde você tocou por último.
4. Toque em "Teclado" de novo para fechar.

O servidor só digita se a **janela ativa estiver no monitor do iPad**; se não estiver, o iPad avisa
"toque antes numa janela que esteja na tela do iPad". Assim o iPad nunca digita na tela principal.

### Segurança

Como o toque controla o mouse e o teclado do PC, há quatro proteções:

- **Chave na URL:** imagem e toque só respondem com a **chave** certa (`?chave=...`); sem ela, o
  servidor responde 403 e não processa clique nenhum. A página abre sem chave, mas avisa em português
  se ela faltar ou estiver errada.
- **Limite de tentativas:** depois de 5 chaves erradas seguidas, aquele aparelho (IP) fica bloqueado
  por 5 minutos (erro 429), mesmo que acerte a chave depois. A janela do servidor avisa quando bloqueia.
- **Nunca a tela principal:** o servidor só transmite um monitor secundário. Para espelhar a principal
  de propósito (teste), use `--monitor 1 --permitir-principal`.
- **Toque e teclado presos ao monitor virtual:** antes de cada tecla, o servidor confere que a janela
  ativa está no monitor do iPad. Antes de cada clique, o servidor confere no Windows que o ponto
  cai no monitor transmitido. Se o monitor sumir com o servidor aberto, o toque é recusado (erro 409)
  em vez de cair na tela principal.

**Só na rede de casa.** Nunca marque como "Rede privada" a rede da faculdade, do trabalho ou de um
café: a regra do firewall liberaria o Tela 2 para todo mundo ali. E **nunca abra a porta 8080 no
roteador** (redirecionamento de porta): o projeto não foi feito para a internet.

#### A chave

- Na primeira execução, o servidor cria uma chave aleatória de 6 dígitos em **`chave.txt`** e
  reutiliza a mesma depois, para o ícone do iPad continuar valendo.
- Para trocar: apague o `chave.txt` ou rode `iniciar.bat --chave 4321`.
  **Depois de trocar (ou na primeira vez que usar a chave), recrie o ícone no iPad uma vez** com a URL nova.
- A conexão é HTTP sem criptografia: a chave evita acessos por acaso na rede de casa, mas não protege
  contra quem capture o tráfego do Wi-Fi. Feche o `iniciar.bat` quando não estiver usando.

### Opções

| Opção | Padrão | Para que serve |
|---|---|---|
| `--fps` | 30 | Quadros por segundo máximos. O iPad 3 recebe uns 15–20 na prática. |
| `--qualidade` | 75 | Qualidade do JPEG (1–95). 60 deixa vídeo um pouco mais fluido e mais borrado. |
| `--largura` | 1024 | Largura máxima da imagem enviada. |
| `--monitor N` | o secundário de 1024 × 768 | Qual monitor transmitir. |
| `--permitir-principal` | desligado | Deixa usar o monitor principal (só para teste de espelhamento). |
| `--porta` | 8080 | Porta do servidor. Se mudar, mude também a regra do firewall. |
| `--chave` | a do `chave.txt` | Chave exigida na URL. |

## Testes

```
python -m unittest discover -s tests -v
```

São 35 testes, só com a biblioteca padrão do Python, rodando a cada push no GitHub Actions (Windows):

- **Chave:** página e ícone abrem sem chave; imagem, stream e toque dão 403 sem chave ou com chave errada.
- **Limite de tentativas:** 5 erros bloqueiam o IP (429), mesmo com a chave certa depois, e bloqueado não clica.
- **Toque:** sem chave nunca chega a clicar; ação desconhecida não clica; monitor que sumiu dá 409 e o mouse não se mexe.
- **Teclado:** sem chave não digita; acentos chegam inteiros; teclas especiais; texto grande demais ou com caractere
  de controle dá 400; janela fora do monitor do iPad dá 409 e nada é digitado.
- **Monitor:** sem monitor virtual o servidor não inicia; a tela principal só com `--permitir-principal`.
- **Chave salva:** 6 dígitos, reutilizada entre execuções, `--chave` substitui.
- **ES5:** o `index.html` não usa `let`, `const`, arrow function, `fetch`, `Promise`, `class`, template string nem WebSocket.

Nenhum teste clica de verdade: a captura de tela e a função que mexe no mouse são trocadas por versões falsas.

## Limitações

- **Fluidez:** ~15–20 fps é o teto prático do iPad 3 (processador de 2012 abrindo um JPEG por quadro,
  mais o Wi-Fi antigo). Dá para usar e ver vídeo, mas não fica liso como um monitor de verdade.
- **Nitidez:** a tela do iPad 3 é 2048 × 1536; o monitor virtual de 1024 × 768 é ampliado 2×.
- **Vídeos 16:9** ficam com faixas pretas em cima e embaixo, porque o iPad é 4:3.
- **Teclado simples:** letras, acentos, apagar, Enter e Tab. Sem atalhos (Ctrl, Alt), sem rolagem com dois dedos
  e sem multitoque.
- O deslocamento da imagem com o teclado aberto foi ajustado para o iPad 3 na horizontal.
- **Só Windows** no PC (captura do cursor e cliques usam a API Win32).
- **Segurança:** HTTP simples na rede local. Não exponha a porta para a internet.

## Problemas comuns

- **A página não abre no iPad:** confira se a rede está como **Privada** e se a regra "Tela 2" existe
  (`netsh advfirewall firewall show rule name="Tela 2"`). PC e iPad no mesmo roteador.
- **"Chave de acesso errada" ou "Falta a chave":** use o endereço completo mostrado na janela do servidor.
- **"Muitas tentativas com chave errada":** espere 5 minutos e abra o endereço certo.
- **"Não achei um monitor secundário de 1024x768":** o monitor virtual sumiu ou mudou de resolução.
  Confira em Configurações > Sistema > Tela e rode `iniciar.bat --listar`.
- **Imagem cortada depois de mudar a resolução:** reinicie o `iniciar.bat`.
- **Uma janela "fugiu" para o monitor virtual:** clique nela na barra de tarefas e aperte **Win + Shift + ←**.
- **Lento:** teste `--qualidade 60` ou o modo `&modo=mjpeg`.
- **Atualização do driver de vídeo:** o projeto do Virtual Display Driver recomenda desinstalá-lo antes,
  para evitar tela preta.

## Créditos e licença

- [Virtual Display Driver](https://github.com/VirtualDrivers/Virtual-Display-Driver), de VirtualDrivers: o monitor virtual.
  Consulte a licença do projeto deles; nenhum arquivo dele está neste repositório.
- [python-mss](https://github.com/BoboTiG/python-mss) e [Pillow](https://python-pillow.org/): captura e JPEG.
- Código do Tela 2 sob a licença [MIT](LICENSE) © 2026 Guilherme Santos Souza.
