FROM python:3.12-alpine

COPY . .

COPY data/opt_out_numbers.txt data/out_out_numbers.txt
COPY static/ static/
COPY templates/ templates/

RUN pip3 install -r requirements.txt
