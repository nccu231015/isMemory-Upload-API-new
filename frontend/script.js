document.addEventListener('DOMContentLoaded', function() {
    const submitBtn = document.getElementById('submit-btn');
    const videoUrlInput = document.getElementById('video-url');
    const loadingSection = document.getElementById('loading');
    const resultsSection = document.getElementById('results');
    
    // 類型切換元素
    const videoTypeBtn = document.getElementById('video-type-btn');
    const imageTypeBtn = document.getElementById('image-type-btn');
    const videoSection = document.getElementById('video-section');
    const imageSection = document.getElementById('image-section');
    
    // 圖片上傳元素
    const imageUpload = document.getElementById('image-upload');
    const uploadArea = document.getElementById('upload-area');
    const imagePreview = document.getElementById('image-preview');
    const previewImg = document.getElementById('preview-img');
    const imageInfo = document.getElementById('image-info');
    const removeImageBtn = document.getElementById('remove-image');
    
    let selectedFile = null;
    let currentAnalysisType = 'video'; // 'video' 或 'image'
    
    // 事件監聽器
    submitBtn.addEventListener('click', startAnalysis);
    videoTypeBtn.addEventListener('click', () => switchAnalysisType('video'));
    imageTypeBtn.addEventListener('click', () => switchAnalysisType('image'));
    
    // 圖片上傳相關事件
    uploadArea.addEventListener('click', () => imageUpload.click());
    imageUpload.addEventListener('change', handleImageSelect);
    removeImageBtn.addEventListener('click', removeSelectedImage);
    
    // 拖拽上傳
    uploadArea.addEventListener('dragover', handleDragOver);
    uploadArea.addEventListener('dragleave', handleDragLeave);
    uploadArea.addEventListener('drop', handleDrop);
    
    // 切換分析類型
    function switchAnalysisType(type) {
        currentAnalysisType = type;
        
        if (type === 'video') {
            videoTypeBtn.classList.add('active');
            imageTypeBtn.classList.remove('active');
            videoSection.classList.remove('hidden');
            imageSection.classList.add('hidden');
            submitBtn.textContent = '分析影片';
        } else {
            imageTypeBtn.classList.add('active');
            videoTypeBtn.classList.remove('active');
            imageSection.classList.remove('hidden');
            videoSection.classList.add('hidden');
            submitBtn.textContent = '分析圖片';
        }
        
        // 清除結果
        resultsSection.classList.add('hidden');
    }
    
    // 處理圖片選擇
    function handleImageSelect(event) {
        const file = event.target.files[0];
        if (file && file.type.startsWith('image/')) {
            selectedFile = file;
            showImagePreview(file);
        } else {
            alert('請選擇有效的圖片檔案');
        }
    }
    
    // 顯示圖片預覽
    function showImagePreview(file) {
        const reader = new FileReader();
        reader.onload = function(e) {
            previewImg.src = e.target.result;
            imageInfo.textContent = `${file.name} (${(file.size / 1024 / 1024).toFixed(2)} MB)`;
            uploadArea.classList.add('hidden');
            imagePreview.classList.remove('hidden');
        };
        reader.readAsDataURL(file);
    }
    
    // 移除選擇的圖片
    function removeSelectedImage() {
        selectedFile = null;
        imageUpload.value = '';
        uploadArea.classList.remove('hidden');
        imagePreview.classList.add('hidden');
        previewImg.src = '';
        imageInfo.textContent = '';
    }
    
    // 拖拽處理
    function handleDragOver(event) {
        event.preventDefault();
        uploadArea.classList.add('dragover');
    }
    
    function handleDragLeave(event) {
        event.preventDefault();
        uploadArea.classList.remove('dragover');
    }
    
    function handleDrop(event) {
        event.preventDefault();
        uploadArea.classList.remove('dragover');
        
        const files = event.dataTransfer.files;
        if (files.length > 0 && files[0].type.startsWith('image/')) {
            selectedFile = files[0];
            showImagePreview(files[0]);
        } else {
            alert('請拖拽有效的圖片檔案');
        }
    }
    
    // 開始分析
    async function startAnalysis() {
        if (currentAnalysisType === 'video') {
            await analyzeVideo();
        } else {
            await analyzeImage();
        }
    }
    
    // 分析影片
    async function analyzeVideo() {
        const url = videoUrlInput.value.trim();
        console.log(`前端獲取的URL: '${url}' (長度: ${url.length})`);
        
        if (!url) {
            alert('請輸入有效的影片連結');
            return;
        }
        
        const storeInDb = document.getElementById('store-in-db').checked;
        
        console.log(`準備發送影片分析請求: url='${url}', storeInDb=${storeInDb}`);
        
        // 顯示載入中
        loadingSection.classList.remove('hidden');
        resultsSection.classList.add('hidden');
        submitBtn.disabled = true;
        
        try {
            const formData = new FormData();
            formData.append('url', url);
            formData.append('store_in_db', storeInDb);
            
            const response = await fetch('/api/process', {
                method: 'POST',
                body: formData
            });
            
            if (!response.ok) {
                const errorData = await response.json();
                throw new Error(errorData.detail || '處理請求時發生錯誤');
            }
            
            const data = await response.json();
            displayResults(data.analysis);
            
        } catch (error) {
            alert('錯誤: ' + error.message);
        } finally {
            loadingSection.classList.add('hidden');
            submitBtn.disabled = false;
        }
    }
    
    // 分析圖片
    async function analyzeImage() {
        if (!selectedFile) {
            alert('請選擇要分析的圖片');
            return;
        }
        
        const storeInDb = document.getElementById('store-in-db').checked;
        
        console.log(`準備發送圖片分析請求: file='${selectedFile.name}', storeInDb=${storeInDb}`);
        
        // 顯示載入中
        loadingSection.classList.remove('hidden');
        resultsSection.classList.add('hidden');
        submitBtn.disabled = true;
        
        try {
            const formData = new FormData();
            formData.append('file', selectedFile);
            formData.append('store_in_db', storeInDb);
            
            const response = await fetch('/api/process', {
                method: 'POST',
                body: formData
            });
            
            if (!response.ok) {
                const errorData = await response.json();
                throw new Error(errorData.detail || '處理請求時發生錯誤');
            }
            
            const data = await response.json();
            displayResults(data.analysis);
            
        } catch (error) {
            alert('錯誤: ' + error.message);
        } finally {
            loadingSection.classList.add('hidden');
            submitBtn.disabled = false;
        }
    }
    
    function displayResults(analysis) {
        // 顯示結果區塊
        resultsSection.classList.remove('hidden');
        
        // 填充資料
        document.getElementById('summary').textContent = analysis.summary;
        document.getElementById('important-time').textContent = analysis.important_time || '無';
        document.getElementById('important-location').textContent = analysis.important_location || '無';
        document.getElementById('ocr-text').textContent = analysis.ocr_text || '無文字內容';
        document.getElementById('caption').textContent = analysis.caption || '無字幕內容';
        
        // 設置原始連結
        const originalLink = document.getElementById('original-link');
        originalLink.href = analysis.original_path;
    }
});