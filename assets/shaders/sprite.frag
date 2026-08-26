#version 330 core
precision mediump float;
out vec4 FragColor;
in highp vec2 TexCoords;
uniform sampler2D sprite_texture;
// Optional colour flash: rgb is the flash colour, a is how strongly to mix it in
// (0 = untinted). Used for the red damage flash. Defaults to no tint.
uniform vec4 sprite_tint;
void main() {
    vec4 texColor = texture(sprite_texture, TexCoords);
    if(texColor.a < 0.1) discard;
    texColor.rgb = mix(texColor.rgb, sprite_tint.rgb, clamp(sprite_tint.a, 0.0, 1.0));
    FragColor = texColor;
}