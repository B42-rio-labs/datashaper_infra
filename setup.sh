#!/bin/sh
set -eu

DEBUG_NETWORK_SUBNET="${DEBUG_NETWORK_SUBNET:-172.24.0.0/16}"

docker network inspect nginx >/dev/null 2>&1 || docker network create nginx
docker network inspect debug >/dev/null 2>&1 || docker network create --internal --subnet "$DEBUG_NETWORK_SUBNET" debug
