#version 330 core
precision highp float;
layout (location = 0) in vec2 aPos;
out vec2 TexCoords;
uniform mat4 projection;
uniform mat4 view;
uniform vec3 sprite_pos_world;
uniform vec2 sprite_size;
// In-plane rotation of the billboard (radians). 0 = upright (default). Used to
// turn a top-down head sprite so it points where the actor is heading, matching
// the 2D map view and the player's own rotating head.
uniform float sprite_rot;
void main() {
    TexCoords = aPos + 0.5;
    float sc = cos(sprite_rot);
    float ss = sin(sprite_rot);
    // Rotate the quad corner in the billboard plane. The texture rides the
    // rotated quad, so the whole image spins on screen.
    vec2 rp = vec2(aPos.x * sc - aPos.y * ss, aPos.x * ss + aPos.y * sc);
    vec3 cameraRight = vec3(view[0][0], view[1][0], view[2][0]);
    vec3 cameraUp = vec3(view[0][1], view[1][1], view[2][1]);
    vec3 worldPos = sprite_pos_world
                  + cameraRight * rp.x * sprite_size.x
                  + cameraUp * rp.y * sprite_size.y;
    gl_Position = projection * view * vec4(worldPos, 1.0);
}