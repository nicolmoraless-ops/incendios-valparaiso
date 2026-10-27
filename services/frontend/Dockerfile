# Imagen del frontend para Kubernetes (en Compose los archivos los sirve el contenedor "lb").
FROM nginxinc/nginx-unprivileged:1.27-alpine
COPY index.html app.js estilos.css /usr/share/nginx/html/
EXPOSE 8080
