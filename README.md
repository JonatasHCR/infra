# infra — Keycloak e portal do login unificado

Este diretorio nao pertence a nenhum dos tres sistemas. Ele sobe o **Keycloak**,
o provedor de identidade unico do inventario, da receita e da despesa, e (a
partir da Fase 1) o **portal** que recebe o usuario depois do login.

O plano completo esta em `~/.claude/plans/adaptive-toasting-ocean.md` (o desenho,
com o porque de cada decisao) e no plano de execucao que o acompanha.

## O `HOST_IP` e o centro de tudo

Nao ha DNS nem TLS: tudo e alcancado por `http://<IP-FIXO>:porta`. Esse IP entra
no `issuer` do realm, nos redirect URIs dos cinco clients e no catalogo do
portal — e a **unica string da qual o sistema inteiro depende**.

Por isso ele vive numa variavel de proposito, `HOST_IP`, e nao espalhado pelo
codigo. Precisa ser IP estatico ou reserva de DHCP: trocar depois exige recriar
o realm e redistribuir o `config.json` do agente Windows em cada maquina.

Os composes sao separados por projeto, e `env_file:` define variavel *dentro do
container* — nao serve para a interpolacao do compose, que so le o `.env` do
proprio diretorio. Entao a linha `HOST_IP=` se repete nos quatro `.env`:

```
python scripts/sync_host_ip.py          # propaga o infra/.env para os 3 projetos
python scripts/sync_host_ip.py --check  # so verifica (util em CI ou antes de subir)
```

O script tambem **avisa** — nao corrige — se o `HOST_IP` nao estiver entre os IPs
da maquina. Autodetectar nao compensa: erra com VPN, Wi-Fi e Ethernet
simultaneos, e o valor detectado ainda teria que chegar ao Keycloak.

## Subir o Keycloak

```bash
cp .env.example .env
# preencha HOST_IP, as senhas e os quatro client secrets:
#   openssl rand -hex 32
python scripts/sync_host_ip.py
docker compose up -d
```

O `keycloak-config` renderiza o realm (substitui `${HOST_IP}` e os secrets) e sai;
so entao o Keycloak sobe e importa. Se faltar variavel, ele para com a mensagem
antes de qualquer coisa subir.

### Verificacao — faca **de outra maquina da rede**, nunca do host

```bash
curl http://$HOST_IP:8080/realms/ufc/.well-known/openid-configuration
```

O campo `issuer` precisa ser **exatamente** `http://$HOST_IP:8080/realms/ufc`.
Se vier `localhost` ou o nome do container, o `KC_HOSTNAME` esta errado — e nada
adiante vai funcionar, porque os apps validam o token contra essa string.
Testar do proprio host esconde justamente esse erro.

## Importar os usuarios existentes

Os tres sistemas ja tem gente cadastrada. O script le os tres bancos, deduplica
por email e cria cada pessoa **sem senha**, com `UPDATE_PASSWORD` obrigatorio —
reset forcado, nenhum hash legado e migrado — associando-a aos grupos dos
sistemas em que ja existia.

```bash
python scripts/import_users.py            # relatorio: quantos, conflitos. Nao escreve.
python scripts/import_users.py --apply    # cria de fato
```

Rode **sem** `--apply` primeiro e resolva a lista de emails divergentes (a mesma
pessoa cadastrada com emails diferentes em sistemas diferentes viraria duas
contas). Os containers de banco dos tres projetos precisam estar de pe — a
leitura e por `docker compose exec`, porque os Postgres da despesa e da receita
nao publicam porta.

O `--apply` e idempotente: quem ja existe no realm e reaproveitado, so os grupos
sao reaplicados.

## Realm como codigo

`keycloak/realm-ufc.json` e a fonte da verdade dos clients, grupos e mappers.
**Nao configure nada pelo console:** o que for clicado fica preso no banco do
Keycloak, e trocar o IP volta a ser trabalho manual — anulando o ganho de
centralizar a variavel. Apagar o volume e subir de novo devolve o realm inteiro.

### Notas do realm — por que cada escolha

O `realm-ufc.json` **nao pode ter comentarios**: o importador do Keycloak rejeita
qualquer campo que nao reconheca (`Unrecognized field ... not marked as
ignorable`) e o boot inteiro falha. Entao as explicacoes ficam aqui.

| Campo | Por que |
|---|---|
| `sslRequired: "none"` | Tudo e `http://<ip>`. O padrao `external` tolera faixas privadas, mas depende do Keycloak enxergar o IP de origem certo atras do Docker; `none` remove a variavel. E a primeira linha a mudar quando houver TLS. Note o valor em **minusculo** — a representacao do realm nao aceita `NONE`. |
| `bruteForceProtected` | Assume o papel do `:lockable` do Devise (receita) e do `LOGIN_RATE_LIMIT` do inventario e da despesa, que deixam de existir nas Fases 2-4. |
| `accessTokenLifespan: 3600` | 60 min com refresh, uniforme nos cinco clients. Limita a janela de uma sessao capturada — a mitigacao que sobra sem TLS. |
| Mapper repetido nos 5 clients | Tentador coloca-lo num client scope compartilhado, mas **declarar `clientScopes` no realm faz o Keycloak deixar de criar os scopes padrao** (`profile`, `email`, `roles`, `web-origins`) e todos os clients quebram. Repetir o mapper e o preco de nao mexer nos padroes. |
| Sem `defaultClientScopes` nos clients | Omitindo, o realm aplica os padroes sozinho. Lista-los a mao so cria uma chance de referenciar um scope que nao existe. |
| `despesa-agent` publico | Roda na maquina de cada usuario, sem navegador e sem callback. Direct Access Grants e o unico fluxo possivel ali. |

### Duas coisas diferentes

| | Onde vive | Exemplo |
|---|---|---|
| **Acesso ao sistema** — pode entrar? | Keycloak, via grupos | "Fulano usa inventario e despesa, mas nao receita" |
| **Papel dentro do sistema** — pode o que? | Banco local de cada app | `tipo='Gestor'`, `role: coordenador`, `ocupacao` por centro de custo |

Os grupos `/apps/inventario`, `/apps/receita` e `/apps/despesa` chegam aos tokens
pela claim `groups`, com **caminho completo** (`full.path: true` no mapper) —
todos os backends e o portal comparam contra `/apps/<sistema>`.

Os papeis continuam locais porque os sistemas os mutam por regra propria (o
inventario troca `user.tipo` quando um Admin aprova solicitacao de cargo) e a
autorizacao real nem usa o papel global: usa a ocupacao **por centro de custo**.

## O contrato do BFF (`portal/lib/`)

O portal foi construido primeiro de proposito: e a aplicacao sem dominio, sem
banco e sem migration onde o padrao novo pode ser acertado barato. `lib/oidc.ts`,
`lib/session.ts` e `middleware.ts` sao o molde que a despesa (Fase 2) e o
inventario (Fase 3) copiam. Tres coisas so apareceram rodando de verdade:

**1. Cookie de sessao nao cabe em um cookie so.** Access + refresh + id token
cifrados dao ~5,1 KB e o limite e 4096 bytes por cookie (nome + valor +
atributos). O Chrome **descarta** o que passa disso sem nenhum erro, e a pessoa
cai num laco de login inexplicavel. Clientes HTTP de script nao aplicam o limite,
entao o teste passa e o navegador quebra. `session.ts` fatia em
`ufc_portal_session.0`, `.1`, ... — como o ASP.NET Core faz. Nos outros dois
sistemas os tokens serao maiores, entao isso importa mais ainda la.

**2. Nunca monte URL publica a partir de `req.url`.** O Next deriva `req.url` do
hostname de bind do servidor, nao do header `Host`. Em container esse hostname e
`0.0.0.0`, e um `new URL('/', req.url)` produz `http://0.0.0.0:3080/` — endereco
que nenhum navegador segue. Use `baseUrl()`, montado do `HOST_IP`.

**3. O refresh mora no middleware.** Um Server Component nao pode gravar cookie:
ele conseguiria renovar o token, mas nao guardar o resultado, e renovaria de novo
a cada request. O middleware e o unico ponto que le a sessao e escreve na
resposta.

Alem disso o fluxo usa **PKCE**, que o desenho original dispensava por o client
ser confidencial. Aqui ele ganha valor: o authorization code volta na URL do
navegador, que trafega em texto claro e pode ser capturado; o `code_verifier`
nunca sai do servidor, entao o codigo sozinho nao serve. Custa dez linhas porque
rodamos no servidor, onde `node:crypto` existe.


## Implantar no servidor

Roteiro completo para subir tudo numa maquina nova.

### 1. Pre-requisito: IP fixo

Reserve o IP no DHCP (ou configure estatico) ANTES de qualquer coisa. Ele entra
no `issuer` do realm e nos redirect URIs — que ficam gravados no banco do
Keycloak. Trocar depois exige recriar o realm e redistribuir o `config.json` do
agente Windows em cada maquina de usuario.

Confira tambem que as portas 8080, 3080, 3030, 3040, 3010, 8010 e 3050 estao livres e
liberadas no firewall.

### 2. Copiar os quatro diretorios

`infra/`, `Gerenciamento_de_inventario/`, `Gerencimento_de_receita/` e
`Sistema_Despesa/` precisam ficar lado a lado, com esses nomes: os caminhos
relativos entre eles estao nos scripts (`../Sistema_Despesa/.env` e afins).

Os `.env` NAO vao junto (estao no .gitignore) — o passo 3 os cria.

### 3. Preencher o `infra/.env` — a fonte da verdade

```bash
cd infra
cp .env.example .env
```

Preencha:

| Variavel | Como |
|---|---|
| `HOST_IP` | o IP fixo do passo 1 |
| `KC_DB_PASSWORD`, `KC_ADMIN_PASSWORD` | `openssl rand -hex 16` |
| `PORTAL_CLIENT_SECRET` e os outros tres | `openssl rand -hex 32`, um valor **diferente** para cada |
| `PORTAL_SESSION_SECRET` | `openssl rand -hex 32` |
| As quatro portas | so mude se precisar; o padrao ja evita as colisoes |

Nos outros tres projetos, copie os `.env.example` e preencha o que e local de
cada um (senha do Postgres, `RAILS_MASTER_KEY`, etc.). Na receita, gere tambem
`SYNC_API_TOKEN` (`openssl rand -hex 32`) — e o token que o inventario usa para
ler os centros de custo.

### 4. Propagar a configuracao compartilhada

```bash
python scripts/sync_host_ip.py
```

Copia do `infra/.env` para os outros tres os **12 valores duplicados**: HOST_IP,
os client secrets, as portas e o token de sync. Faz isso porque `env_file:` nao
serve para a interpolacao do compose — cada projeto so le o `.env` do proprio
diretorio.

Repita este comando sempre que mudar qualquer um desses valores. O
`--check` verifica sem escrever (util antes de subir, ou em CI).

> A armadilha que ele resolve: a porta do inventario se chama `INVENTARIO_PORT`
> aqui e `FRONTEND_PORT` no `.env` dele. Nomes diferentes, mesmo valor — se
> divergirem, o Keycloak recusa o `redirect_uri` com um "Invalid parameter" que
> nao explica nada.

### 5. Subir, na ordem

```bash
cd infra                       && docker compose up -d    # Keycloak + portal
cd ../Gerencimento_de_receita  && docker compose up -d    # antes do inventario:
                                                          # o sync depende da API dela
cd ../Gerenciamento_de_inventario && docker compose up -d
cd ../Sistema_Despesa          && docker compose up -d
```

O primeiro boot do Keycloak leva ~2 minutos (augmentation do Quarkus + criacao
do schema). O `start_period` do healthcheck ja contempla isso.

### 6. Verificar — **de outra maquina da rede**

```bash
curl http://$HOST_IP:8080/realms/ufc/.well-known/openid-configuration
```

O `issuer` precisa ser exatamente `http://$HOST_IP:8080/realms/ufc`. Testar do
proprio servidor esconde justamente o erro mais comum.

### 7. Importar os usuarios

```bash
cd infra
python scripts/import_users.py            # relatorio; nao escreve nada
python scripts/import_users.py --apply
```

Rode sem `--apply` primeiro e resolva a lista de emails divergentes. Todo mundo
entra sem senha, com `UPDATE_PASSWORD` obrigatorio — define a sua no primeiro
acesso.

### 8. Papeis e primeira carga

Os papeis sao locais e nao vem do Keycloak — grupo e acesso, papel e poder
dentro do sistema.

**O caminho curto e a conta mestra:** um unico email, no `infra/.env`, que
administra os tres sistemas de uma vez.

```bash
# com ADMIN_MESTRE_EMAIL e ADMIN_MESTRE_SENHA preenchidos no infra/.env:
python scripts/criar_admin_mestre.py --apply
python scripts/sync_host_ip.py    # leva o email aos 3 .env
```

Nao e o `KC_ADMIN` (aquele e do console, no realm `master`, e nao entra em
sistema nenhum), nao e papel do Keycloak e nao e grupo — e so este endereco.
Ver a secao "Papeis e primeira carga" do runbook de atualizacao para o
raciocinio completo.

**Ou promova pessoa por pessoa:**

```bash
cd ../Gerenciamento_de_inventario && docker compose exec backend python create_admin.py fulano@empresa.com
cd ../Sistema_Despesa             && docker compose exec backend python promover_admin.py fulano@empresa.com
cd ../Gerencimento_de_receita     && docker compose exec web bin/rails admin:create ADMIN_EMAIL=fulano@empresa.com
```

A pessoa precisa **ja ter entrado uma vez**: os scripts promovem uma linha
existente, e ela so nasce no primeiro login (JIT).

E esse papel que abre a tela **Administracao** (`/administracao` no inventario e
na despesa; painel de manutencao na receita), com backup, restauracao e limpeza
sem linha de comando. As rotas `/manutencao` respondem 403 a quem nao tem o
papel, mesmo digitando a URL — a tela escondida e conveniencia, o gate e no
backend. Nenhuma delas promove ninguem, de proposito.

E dispare a primeira sincronizacao de centros de custo sem esperar os 15 min:

```bash
cd ../Gerenciamento_de_inventario && docker compose run --rm sync python sync_receita.py
```

### 9. Agente Windows

Nao le o `.env` do servidor — roda na maquina de cada pessoa. Atualize o
`config.json` de cada instalacao com `base_url` (`:8010`), `keycloak_url` e as
credenciais. Ver `Sistema_Despesa/agent/README.md`.

### Se o IP mudar depois

1. `HOST_IP` no `infra/.env`
2. `python scripts/sync_host_ip.py`
3. `cd infra && docker compose down -v && docker compose up -d` — **o `-v` e
   necessario**: os redirect URIs vivem no banco do Keycloak, e sem apagar o
   volume o realm antigo continua valendo
4. recriar os outros: `docker compose up -d --force-recreate`
5. redistribuir o `config.json` do agente


## Atualizar uma produção que já existe

O roteiro acima é para máquina nova. Se os três sistemas **já rodam com dados e
usuários reais**, é uma migração, não uma instalação — e a ordem importa.

> **Todo mundo vai precisar redefinir a senha.** Nenhum hash antigo é migrado; é
> o reset forçado que o desenho decidiu. Avise antes: no dia da virada ninguém
> entra com a senha que usava.

### 1. Backup dos três bancos

As migrations não apagam nada — só `add_column`, `add_index` e `alter_column`
no caminho de ida, com os `drop` restritos ao `downgrade`. Ainda assim, a
virada é grande o bastante:

```bash
cd Gerenciamento_de_inventario && docker compose --profile backup run --rm db-backup /scripts/backup.sh
cd ../Sistema_Despesa          && docker compose --profile backup run --rm db-backup /scripts/backup.sh
cd ../Gerencimento_de_receita  && docker compose -f docker-compose.prod.yml exec web bin/rails db:dump  # ou o sidecar de backup
```

### 2. Código novo

`git pull` nos três repositórios. O `infra/` é copiado à mão — **sem o `.env`**:
os segredos de desenvolvimento não servem em produção e não devem viajar.

### 3. Segredos NOVOS no `infra/.env`

```bash
cd infra && cp .env.example .env
```

Gere valores **novos** (`openssl rand -hex 32`) para os quatro client secrets,
os dois session secrets e as senhas do Keycloak. Reaproveitar os de
desenvolvimento colocaria em produção segredos que já circularam.

O `HOST_IP` é o IP fixo do servidor de produção.

### 4. Portas — confira antes de gerar o realm

É o passo em que mais se erra, porque o valor tem de bater em dois lugares: a
porta publicada pelo compose e o redirect URI gravado no realm.

| Sistema | Onde a porta é publicada | Variável no `infra/.env` |
|---|---|---|
| Portal | `infra/docker-compose.yml` | `PORTAL_PORT` (3080) |
| Inventário | `FRONTEND_PORT` no `.env` dele | `INVENTARIO_PORT` |
| Receita | `docker-compose.prod.yml` | `RECEITA_PORT` — **use o valor que `WEB_PORT` tinha** (tipicamente 80) |
| Despesa (radar) | fixo no compose | `DESPESA_PORT` (3010) |
| Controle de Despesa | `docker-compose.yml` dele | `CONTROLE_DESPESA_PORT` (3050) |

**A despesa muda de porta:** backend 8000 → **8010**, frontend 3000 → **3010**,
porque colidiam com o inventário. Ajuste o firewall e avise quem tem favorito.

Depois:

```bash
python scripts/sync_host_ip.py     # propaga IP, secrets e portas para os 3 .env
python scripts/sync_host_ip.py --check
```

Na receita ainda falta o `SYNC_API_TOKEN` (`openssl rand -hex 32`), que nasce no
`.env` dela; rode o `sync_host_ip.py` de novo depois de criá-lo, para o
inventário receber o mesmo valor.

### 5. Keycloak no ar, e conferido de OUTRA máquina

```bash
cd infra && docker compose up -d
curl http://$HOST_IP:8080/realms/ufc/.well-known/openid-configuration
```

O `issuer` tem de ser exatamente `http://$HOST_IP:8080/realms/ufc`. Testar do
próprio servidor esconde o erro mais comum.

### 6. Importar os usuários que já existem

```bash
python scripts/import_users.py            # relatório; não escreve nada
python scripts/import_users.py --apply
```

Rode **sem** `--apply` primeiro e resolva a lista de emails divergentes: a mesma
pessoa com emails diferentes em sistemas diferentes viraria duas contas.

Cada pessoa já entra nos grupos dos sistemas em que existia, então os cartões do
portal aparecem certos desde o começo.

### 7. Subir os três sistemas

As migrations rodam sozinhas: `alembic upgrade head` está no CMD do inventário e
da despesa, e o `db:prepare` no comando da receita.

```bash
cd Gerenciamento_de_inventario && docker compose up -d --build
cd ../Sistema_Despesa          && docker compose up -d --build
cd ../Gerencimento_de_receita  && docker compose -f docker-compose.prod.yml up -d --build
```

Confira que ninguém foi desativado pela migração — a coluna `ativo` nasce com
default `true`:

```sql
SELECT count(*), count(*) FILTER (WHERE ativo) FROM tb_users;   -- inventário e despesa
SELECT count(*), count(*) FILTER (WHERE ativo) FROM users;      -- receita
```

### 8. Papéis e primeira carga

Os papéis são locais e não vêm do Keycloak — grupo é acesso, papel é poder
dentro do sistema.

**O caminho curto é a conta mestra.** Um único email, no `infra/.env`, que é
administrador dos três sistemas ao mesmo tempo — para não ser preciso manter
três contas só para administrar:

```bash
# preencha ADMIN_MESTRE_EMAIL e ADMIN_MESTRE_SENHA no infra/.env, e entao:
python scripts/criar_admin_mestre.py --apply   # cria a conta no realm ufc
python scripts/sync_host_ip.py                 # leva o email aos 3 .env
# recrie os tres sistemas para lerem a variavel nova
```

Três coisas que essa conta **não** é:

- Não é o `KC_ADMIN`. Aquele vive no realm `master`, é do console do Keycloak,
  e não consegue entrar em nenhum dos três sistemas.
- Não é papel do Keycloak. Ser admin do console não dá poder algum dentro dos
  sistemas.
- Não é grupo. Estar em `/admins` não torna ninguém administrador de sistema
  nenhum — é só este endereço, comparado por igualdade.

Ela também **não depende de grupo para entrar**: sem essa exceção, tirar a si
mesmo de um grupo por engano trancaria a porta justamente de quem conserta, e o
conserto é na tela de acessos, atrás dessa mesma porta.

> Consequência a conhecer: quem administra o realm pode trocar o email de uma
> conta, e com isso tornar-se admin dos três sistemas. Um admin do realm já é a
> pessoa mais privilegiada do conjunto, mas mantenha esse círculo pequeno.

O script é idempotente e serve tanto para uma instalação nova quanto para uma
produção que já existe — o `--import-realm` só roda quando o realm ainda não
existe, então semear a conta no `realm-ufc.json` não teria efeito num servidor
que já está no ar.

**Ou, promovendo pessoa por pessoa,** o caminho longo:

```bash
docker compose exec backend python create_admin.py fulano@empresa.com          # inventário
docker compose exec backend python promover_admin.py fulano@empresa.com        # despesa
docker compose -f docker-compose.prod.yml exec web bin/rails admin:create ADMIN_EMAIL=fulano@empresa.com
```

> A pessoa precisa **já ter entrado uma vez** no sistema: os três scripts
> promovem uma linha existente, e a linha só nasce no primeiro login (JIT).

É esse papel que abre a tela **Administração** (backup, restauração e limpeza)
em `/administracao` no inventário e na despesa, e o painel de manutenção da
receita. Sem ele o link nem aparece no menu — e, mais importante, as rotas
`/manutencao` respondem 403 mesmo que alguém digite a URL à mão. Nenhuma das
telas promove ninguém, de propósito: quem tivesse acesso a ela se promoveria.

Os arquivos caem em `./backups` de cada projeto — a mesma pasta do sidecar
agendado, então os automáticos e os do botão aparecem na mesma lista.

E dispare a primeira sincronização de centros de custo sem esperar os 15 min:

```bash
cd Gerenciamento_de_inventario && docker compose run --rm sync python sync_receita.py
```

> **Antes do primeiro sync**, confira se algum contrato local do inventário tem
> o mesmo código de um CC da receita — se tiver, a descrição dele será
> substituída pela de lá:
> ```sql
> SELECT centro_custo, descricao FROM tb_contratos WHERE sincronizado_em IS NULL;
> ```

### 9. Agente Windows, em cada máquina

É o único lugar que não lê o `.env` do servidor. Atualize o `config.json` de
cada instalação: `base_url` para a porta **8010**, `keycloak_url`, `client_id` e
as credenciais do Keycloak. Ver `Sistema_Despesa/agent/README.md`.

### 10. Aviso às pessoas

No primeiro acesso, cada uma define a senha (o Keycloak pede). O caminho passa a
ser **o portal**, não a URL de cada sistema — embora as URLs antigas continuem
funcionando e levem ao login.

## Risco aceito: trafego em texto claro

Sem TLS, tudo entre navegador e servidores anda sem cifra na rede interna —
inclusive o cookie de sessao e a senha digitada na tela de login do Keycloak.
Quem tiver um sniffer no mesmo segmento captura o cookie e assume a sessao.

O desenho reduz o que da: cookie `httpOnly` (protege de XSS, nao de sniffing),
padrao BFF (o access token nunca chega ao navegador), token de 60 min, e
`SameSite=Lax`. O que nao da para fazer e a flag `Secure` no cookie.

Em rede cabeada com switch gerenciado o risco e moderado. **Se houver Wi-Fi no
caminho, e serio** — vale reconsiderar a decisao de rede.

Quando houver TLS, a arquitetura nao muda: um proxy TLS na frente, as URLs nos
redirect URIs, o `KC_HOSTNAME`, e `Secure` no cookie. Horas de trabalho.

## Portas

| Servico | Porta |
|---|---|
| Keycloak | 8080 |
| Portal (Fase 1) | 3080 |
| Inventario frontend | 3000 |
| Receita | 3040 |
| Despesa frontend (radar) | 3010 |
| Despesa backend (radar) | 8010 |
| Controle de Despesa | 3050 |
