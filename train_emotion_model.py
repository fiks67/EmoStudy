import os
import matplotlib.pyplot as plt
import tensorflow as tf
from tensorflow.keras.models import Sequential
from tensorflow.keras.layers import Conv2D, MaxPool2D, Flatten, Dense, Dropout, BatchNormalization
from tensorflow.keras.preprocessing.image import ImageDataGenerator
from tensorflow.keras.optimizers import Adam

# ── Config ──
TRAIN_DIR  = "../emotionapp/dataset/train"
IMG_SIZE   = 48
BATCH_SIZE = 128
EPOCHS     = 50

# ── Data generators ──
# Fix: val_datagen MUST have validation_split and NO augmentation
train_datagen = ImageDataGenerator(
    rescale=1./255,
    validation_split=0.2,
    horizontal_flip=True,
    rotation_range=15,
    width_shift_range=0.15,
    height_shift_range=0.15,
    zoom_range=0.15,
    brightness_range=[0.7, 1.3],
    shear_range=0.1,
)
val_datagen = ImageDataGenerator(
    rescale=1./255,
    validation_split=0.2,   # Fix: wajib ada agar subset="validation" bisa dipakai
)

train_generator = train_datagen.flow_from_directory(
    directory=TRAIN_DIR,
    target_size=(IMG_SIZE, IMG_SIZE),
    batch_size=BATCH_SIZE,
    color_mode="grayscale",
    class_mode="categorical",
    subset="training",
    seed=42,
)
val_generator = val_datagen.flow_from_directory(   # Fix: pakai val_datagen, bukan train_datagen
    directory=TRAIN_DIR,
    target_size=(IMG_SIZE, IMG_SIZE),
    batch_size=BATCH_SIZE,
    color_mode="grayscale",
    class_mode="categorical",
    subset="validation",
    seed=42,
)

# ── Class weights (computed from folder counts to handle imbalance) ──
class_names = sorted(os.listdir(TRAIN_DIR))
class_counts = {
    i: len(os.listdir(os.path.join(TRAIN_DIR, name)))
    for i, name in enumerate(class_names)
}
total = sum(class_counts.values())
n_classes = len(class_counts)
class_weight = {
    cls: (total / (n_classes * count))
    for cls, count in class_counts.items()
}
print("Classes :", class_names)
print("Counts  :", class_counts)
print("Weights :", {k: round(v, 3) for k, v in class_weight.items()})

# ── Model ──
model = Sequential([
    Conv2D(64,  (3,3), padding='same', activation='relu', input_shape=(IMG_SIZE, IMG_SIZE, 1)),
    MaxPool2D(2, 2),
    BatchNormalization(),

    Conv2D(128, (3,3), padding='same', activation='relu'),
    MaxPool2D(2, 2),
    BatchNormalization(),
    Dropout(0.25),

    Conv2D(256, (3,3), padding='same', activation='relu'),
    MaxPool2D(2, 2),
    BatchNormalization(),
    Dropout(0.25),

    Flatten(),
    Dense(128, activation='relu', kernel_initializer='he_normal'),
    BatchNormalization(),
    Dropout(0.4),
    Dense(7,   activation='softmax'),
])

model.compile(
    optimizer=Adam(learning_rate=0.001),
    loss='categorical_crossentropy',
    metrics=['accuracy'],
)
model.summary()

# ── Callbacks ──
callbacks = [
    tf.keras.callbacks.ModelCheckpoint(
        "model_best.keras", monitor="val_accuracy", save_best_only=True, verbose=1
    ),
    tf.keras.callbacks.ReduceLROnPlateau(
        monitor="val_loss", factor=0.5, patience=4, min_lr=1e-6, verbose=1
    ),
    tf.keras.callbacks.EarlyStopping(
        monitor="val_accuracy", patience=10, restore_best_weights=True, verbose=1
    ),
    tf.keras.callbacks.CSVLogger("training_log.csv"),
]

# ── Training ──
history = model.fit(
    train_generator,
    epochs=EPOCHS,
    validation_data=val_generator,
    class_weight=class_weight,   # Fix: handle imbalance
    callbacks=callbacks,
)

# ── Plot ──
fig, ax = plt.subplots(1, 2, figsize=(12, 4))
ax[0].plot(history.history['accuracy'],     label='Train')
ax[0].plot(history.history['val_accuracy'], label='Validation')
ax[0].set_title('Accuracy')
ax[0].legend()
ax[1].plot(history.history['loss'],     label='Train')
ax[1].plot(history.history['val_loss'], label='Validation')
ax[1].set_title('Loss')
ax[1].legend()
plt.tight_layout()
plt.savefig("training_plot.png", dpi=150)
plt.show()

# ── Evaluate ──
train_loss, train_acc = model.evaluate(train_generator)
val_loss,   val_acc   = model.evaluate(val_generator)
print(f"\nTrain accuracy     : {train_acc*100:.2f}%")
print(f"Validation accuracy: {val_acc*100:.2f}%")

# ── Save ──
model.save("model_final.keras")
model.save_weights("model_weights.weights.h5")
print("\n✓ model_best.keras  — best checkpoint")
print("✓ model_final.keras — last epoch")
print("✓ training_plot.png")
print("✓ training_log.csv")
