shader_type canvas_item;

// a comment with uniform float fake = 1.0;
uniform int count = 3;
uniform bool on = true;
uniform vec2 offset = vec2(1.0, 0.5);
uniform vec3 axis = vec3(0.0, 1.0, 0.0);
uniform vec4 plain4 = vec4(0.25, 0.5, 0.75, 1.0);
uniform vec3 rgb : source_color = vec3(1.0, 0.5, 0.25);
uniform float tenth = 0.1;
uniform float ranged : hint_range(0.0, 2.0) = 1.0;
uniform float bare;
uniform ivec2 cells = ivec2(2, 3);
instance uniform float per_inst = 2.0;
group_uniforms extra;
uniform float grouped = 0.5;
group_uniforms;
