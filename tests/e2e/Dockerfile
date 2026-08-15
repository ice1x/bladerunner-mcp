FROM alpine:3.20
RUN apk add --no-cache openssh rsync \
 && ssh-keygen -A \
 && adduser -D -s /bin/sh test \
 && sed -i 's/^test:!/test:*/' /etc/shadow \
 && mkdir -p /home/test/.ssh && chmod 700 /home/test/.ssh
COPY keys/id_test.pub /home/test/.ssh/authorized_keys
RUN chown -R test:test /home/test/.ssh && chmod 600 /home/test/.ssh/authorized_keys
CMD ["/usr/sbin/sshd", "-D", "-e"]
