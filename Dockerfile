FROM python:3.13-slim
WORKDIR /opt/pareto-support-proofs
COPY . .
RUN python -m pip install --no-cache-dir --upgrade pip setuptools wheel \
    && python -m pip install --no-cache-dir -r requirements-validation.txt \
    && python -m pip install --no-cache-dir --no-build-isolation .
ENV PYTHONHASHSEED=0 \
    OPENBLAS_NUM_THREADS=1 \
    OMP_NUM_THREADS=1 \
    MKL_NUM_THREADS=1
CMD ["python", "scripts/run_release_validation.py"]
