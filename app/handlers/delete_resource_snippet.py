async def delete_resource_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    /delete_resource <id> - 删除资源
    
    权限：上传者本人或管理员
    """
    if not update.message or not context.args:
        await update.message.reply_text(
            "用法: /delete_resource <资源ID>\n\n"
            "例如: /delete_resource 123"
        )
        return
    
    try:
        resource_id = int(context.args[0])
    except ValueError:
        await update.message.reply_text("❌ 资源ID必须是数字")
        return
    
    # 检查管理员权限
    from app.handlers.commands import is_admin
    user_is_admin = await is_admin(update)
    
   user_id = update.effective_user.id
    
    # 执行删除
    with Session(engine) as session:
        success, message = ResourceService.delete_resource(
            session=session,
            resource_id=resource_id,
            user_id=user_id,
            is_admin=user_is_admin
        )
        
        if success:
            await update.message.reply_text(f"✅ {message}")
        else:
            await update.message.reply_text(f"❌ {message}")
