#!/bin/sh
# Renderiza o realm-ufc.json substituindo os placeholders ${VAR} pelos valores
# do ambiente, e escreve o resultado onde o Keycloak vai procurar no boot.
#
# Roda num container alpine separado, nao dentro do Keycloak: a imagem oficial
# e minima e nao ha garantia de sed/envsubst nela.  Assim o render nao depende
# de nada do que houver dentro da imagem do Keycloak.
set -eu

TEMPLATE=/template/realm-ufc.json
OUT=/out/realm-ufc.json

VARS="HOST_IP PORTAL_PORT INVENTARIO_PORT RECEITA_PORT DESPESA_PORT CONTROLE_DESPESA_PORT
      PORTAL_CLIENT_SECRET INVENTARIO_CLIENT_SECRET RECEITA_CLIENT_SECRET DESPESA_CLIENT_SECRET
      CONTROLE_DESPESA_CLIENT_SECRET"

for v in $VARS; do
  eval "val=\${$v:-}"
  if [ -z "$val" ]; then
    echo "ERRO: $v esta vazia. Preencha o infra/.env antes de subir." >&2
    exit 1
  fi
done

cp "$TEMPLATE" "$OUT"
for v in $VARS; do
  eval "val=\${$v}"
  # '|' como delimitador: o HOST_IP nao contem '|', mas contem '.'
  sed -i "s|\${$v}|$val|g" "$OUT"
done

# Rede de seguranca: um placeholder esquecido viraria redirect URI invalido e o
# login falharia com um erro obscuro do Keycloak, horas depois.
if grep -q '\${' "$OUT"; then
  echo "ERRO: sobrou placeholder nao substituido no realm:" >&2
  grep -n '\${' "$OUT" >&2
  exit 1
fi

echo "realm-ufc.json renderizado para HOST_IP=$HOST_IP"
