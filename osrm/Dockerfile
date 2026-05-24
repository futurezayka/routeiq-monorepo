FROM osrm/osrm-backend:v5.25.0

RUN echo 'deb http://archive.debian.org/debian stretch main' > /etc/apt/sources.list \
 && echo 'deb http://archive.debian.org/debian-security stretch/updates main' >> /etc/apt/sources.list \
 && apt-get -o Acquire::Check-Valid-Until=false update \
 && apt-get install -y --no-install-recommends wget curl ca-certificates \
 && update-ca-certificates \
 && rm -rf /var/lib/apt/lists/*

COPY prepare.sh /prepare.sh
RUN chmod +x /prepare.sh

VOLUME /data
EXPOSE 5000

CMD ["/bin/bash", "-c", "/prepare.sh && osrm-routed --algorithm mld /data/kyiv.osrm --port 5000"]
