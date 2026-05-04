#!/bin/sh
set -eu

docker network inspect nginx >/dev/null 2>&1 || docker network create nginx
docker network inspect debug >/dev/null 2>&1 || docker network create --internal debug
