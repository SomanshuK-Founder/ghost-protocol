FROM scratch
ADD rootfs.tar /
USER 1000:1000
WORKDIR /work
ENTRYPOINT ["/opt/ghost-probe/probe"]
CMD ["identity"]
LABEL org.ghost-protocol.purpose="synthetic-openshell-security-probe"
