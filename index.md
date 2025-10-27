Here you can say lots of fun things about your site.

Maybe say a some things about yourself.

Or maybe what you plan to blog about.

{% for tag in site.tags %}
  {% assign t = tag | first %}
  {% assign posts = tag | last %}
  <li>{{t | downcase | replace:" ","-" }} has {{ posts | size }} posts</li>
{% endfor %}