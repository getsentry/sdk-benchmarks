FROM postgres:16-alpine
COPY init.sql /docker-entrypoint-initdb.d/
ENV POSTGRES_USER=benchmarkdbuser
ENV POSTGRES_PASSWORD=benchmarkdbpass
ENV POSTGRES_DB=hello_world
