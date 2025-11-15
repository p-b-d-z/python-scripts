FROM python:3.12-alpine
ARG USER_ID=1000
ARG GROUP_ID=1000

RUN addgroup -g ${GROUP_ID} -S user \
    && adduser -u ${USER_ID} -G user -S user

COPY . .

COPY data/opt_out_numbers.txt data/out_out_numbers.txt
COPY static/ static/
COPY templates/ templates/

RUN pip3 install -r requirements.txt
