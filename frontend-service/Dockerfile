# nginx:alpine — 8MB image, purpose-built for serving static files
# No Python, no Node.js, no build step needed
FROM nginx:alpine

# Remove the default nginx welcome page
RUN rm -rf /usr/share/nginx/html/*

# Copy our frontend HTML/CSS/JS files
COPY frontend/ /usr/share/nginx/html/

# Copy our custom nginx configuration
COPY nginx.conf /etc/nginx/conf.d/default.conf

# nginx listens on port 80
EXPOSE 80

# No CMD needed — nginx:alpine base image starts nginx automatically
