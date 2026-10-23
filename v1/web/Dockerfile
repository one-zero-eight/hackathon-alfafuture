# Build context: the repository root.
FROM node:22-alpine AS build
WORKDIR /app
COPY ui/package.json ui/package-lock.json ./
RUN npm ci
COPY ui/ .
RUN npm run build

FROM nginx:1.29-alpine
COPY --from=build /app/dist /usr/share/nginx/html
COPY v1/web/nginx.conf /etc/nginx/conf.d/default.conf
