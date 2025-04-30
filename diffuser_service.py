from diffusers import DiffusionPipeline

def try_out_outfit():

    pipe = DiffusionPipeline.from_pretrained("yisol/IDM-VTON")

    prompt = "Astronaut in a jungle, cold color palette, muted colors, detailed, 8k"
    image = pipe(prompt).images[0]
    print(image)

try_out_outfit()