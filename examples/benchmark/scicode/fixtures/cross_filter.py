import numpy as np

def apply_cshband_pass_filter(image_array, bandwidth):
    height, width = image_array.shape
    x = np.arange(width) - width // 2
    y = np.arange(height) - height // 2
    T = ((np.abs(y[:, None]) > bandwidth) & (np.abs(x[None, :]) > bandwidth)).astype(float)
    transformed = np.fft.fftshift(np.fft.fft2(image_array))
    filtered_image = np.fft.ifft2(np.fft.ifftshift(transformed * T)).real
    return T, filtered_image
