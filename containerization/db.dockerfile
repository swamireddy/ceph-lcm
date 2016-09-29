# vi: set ft=dockerfile :


FROM mongo:3.2.9
MAINTAINER Sergey Arkhipov <sarkhipov@mirantis.com>


COPY containerization/files/mongod.conf /etc/mongod.conf


CMD ["--config", "/etc/mongod.conf"]