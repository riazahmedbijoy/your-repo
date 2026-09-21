FROM node:20-alpine

WORKDIR /app

RUN apk add --no-cache git
RUN git clone --single-branch --branch 2.0.0 https://github.com/Brainicism/bgutil-ytdlp-pot-provider.git .

WORKDIR /app/server
RUN npm ci && npx tsc

EXPOSE 4416

CMD ["node", "build/main.js"]
