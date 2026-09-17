<template>
  <div class="stars" ref="starsRef"></div>
</template>

<script setup lang="ts">
import { onMounted, ref } from 'vue'

const starsRef = ref<HTMLElement>()

onMounted(() => {
  createStars()
})

function createStars() {
  if (!starsRef.value) return
  
  // 创建星星，增加数量让效果更明显
  for (let i = 0; i < 80; i++) {
    const star = document.createElement('div')
    star.className = 'star'
    star.style.left = Math.random() * 100 + '%'
    star.style.top = Math.random() * 100 + '%'
    star.style.animationDelay = Math.random() * 3 + 's'
    star.style.animationDuration = (Math.random() * 2 + 2) + 's'
    starsRef.value.appendChild(star)
  }
}
</script>

<style scoped>
.stars {
  position: fixed;
  width: 100%;
  height: 100%;
  top: 0;
  left: 0;
  overflow: hidden;
  z-index: 0;
  pointer-events: none;
}

.star {
  position: absolute;
  width: 2px;
  height: 2px;
  background: white;
  border-radius: 50%;
  box-shadow: 0 0 4px rgba(255, 255, 255, 0.8), 0 0 8px rgba(255, 255, 255, 0.4);
  animation: twinkle 3s infinite;
  will-change: opacity;
}

@keyframes twinkle {
  0%, 100% { 
    opacity: 0.5; 
    transform: scale(1);
  }
  50% { 
    opacity: 1; 
    transform: scale(1.2);
  }
}
</style>
