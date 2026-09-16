# Reproducible brochure build environment
FROM debian:bookworm-slim
RUN apt-get update && apt-get install -y --no-install-recommends \
      texlive-luatex texlive-latex-base texlive-latex-recommended \
      texlive-latex-extra texlive-pictures texlive-fonts-extra \
      poppler-utils python3 \
 && rm -rf /var/lib/apt/lists/*
WORKDIR /work/brochure
ENTRYPOINT ["python3", "tools/build.py"]
